#include "relay.h"

#include "esp_log.h"
#include "host/ble_gap.h"
#include "host/ble_gatt.h"
#include "host/ble_hs.h"
#include "host/ble_uuid.h"
#include "host/util/util.h"
#include "nimble/ble.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "os/os_mbuf.h"
#include "services/gap/ble_svc_gap.h"

#include <stdio.h>
#include <string.h>

enum { RESET_ATTR = 0xFFFF };

static const char *TAG = "ble";


typedef struct {
  int      disconnect_after;
  uint32_t epoch;
  uint8_t  sequence;
  uint8_t  unit;
} ack_request_t;

static int                  s_ack_active;
static struct ble_npl_event  s_ack_event;
static ack_request_t        s_ack_request;
static QueueHandle_t        s_ack_requests;
static SemaphoreHandle_t s_ble_lock;
static uint16_t          s_conn;
static uint16_t          s_svc_start;
static uint16_t          s_svc_end;
static uint16_t          s_ffb1;
static uint16_t          s_ffb2;
static uint16_t          s_ffb3;
static uint16_t          s_ffb2_ccc;
static uint16_t          s_ffb3_ccc;
static uint16_t          s_ffb2_end;
static uint16_t          s_ffb3_end;
static uint8_t           s_ack_seq;
static uint32_t          s_epoch;
static int               s_connected;
static int               s_have_svc;
static ble_addr_t        s_peer;
/* Configured or learned scale address; empty until auto-pairing learns one. */
static char              s_scale_addr[18];

static void scan_start(void);

/* The scale uses Bluetooth-base 128-bit UUIDs for its vendor service and
 * characteristics. NimBLE's ble_uuid_u16 does not shorten that encoding. */
static uint16_t scale_uuid16(const ble_uuid_t *uuid) {
  if (uuid->type == BLE_UUID_TYPE_128) {
    return bluetooth_uuid128_to_u16(BLE_UUID128(uuid)->value);
  }
  return ble_uuid_u16(uuid);
}

static void lock_ble(void) {
  xSemaphoreTake(s_ble_lock, portMAX_DELAY);
}

static void unlock_ble(void) {
  xSemaphoreGive(s_ble_lock);
}

static void queue_reset(void) {
  ble_frame_msg_t msg = {.attr = RESET_ATTR, .epoch = s_epoch};
  xQueueReset(g_ble_frames);
  xQueueReset(s_ack_requests);
  s_ack_active = 0;
  xQueueSend(g_ble_frames, &msg, 0);
}

static void clear_session_locked(void) {
  s_svc_start = s_svc_end = 0;
  s_ffb1 = s_ffb2 = s_ffb3 = s_ffb2_ccc = s_ffb3_ccc = 0;
  s_ffb2_end = s_ffb3_end = 0;
  s_ack_seq      = 0;
  s_have_svc     = 0;
}

static int parse_mac(const char *text, ble_addr_t *addr) {
  unsigned b[6];
  if (sscanf(text, "%02x:%02x:%02x:%02x:%02x:%02x", &b[0], &b[1], &b[2], &b[3], &b[4],
             &b[5]) != 6) {
    return -1;
  }
  addr->type   = BLE_ADDR_PUBLIC;
  addr->val[0] = (uint8_t)b[5];
  addr->val[1] = (uint8_t)b[4];
  addr->val[2] = (uint8_t)b[3];
  addr->val[3] = (uint8_t)b[2];
  addr->val[4] = (uint8_t)b[1];
  addr->val[5] = (uint8_t)b[0];
  return 0;
}

/* Caller holds the BLE lock. */
static int scale_match(const struct ble_gap_disc_desc *disc) {
  ble_addr_t want;
  if (s_scale_addr[0] == 0) {
    struct ble_hs_adv_fields fields;
    return ble_hs_adv_parse_fields(&fields, disc->data, disc->length_data) == 0 &&
           scale_name_matches(fields.name, fields.name_len);
  }
  if (parse_mac(s_scale_addr, &want) != 0) {
    return 0;
  }
  return memcmp(disc->addr.val, want.val, 6) == 0;
}

/* A device-information packet proves the peer is a scale: keep its address. */
static void learn_scale(void) {
  usb_config_t cfg;
  char         addr[18];

  lock_ble();
  if (s_scale_addr[0] != 0 || !s_connected) {
    unlock_ble();
    return;
  }
  snprintf(addr, sizeof(addr), "%02X:%02X:%02X:%02X:%02X:%02X", s_peer.val[5], s_peer.val[4],
           s_peer.val[3], s_peer.val[2], s_peer.val[1], s_peer.val[0]);
  memcpy(s_scale_addr, addr, sizeof(addr));
  unlock_ble();
  xSemaphoreTake(g_lock, portMAX_DELAY);
  memcpy(g_relay.cfg.scale_address, addr, sizeof(addr));
  cfg = g_relay.cfg;
  xSemaphoreGive(g_lock);
  if (store_save_config(&cfg) != ESP_OK) {
    ESP_LOGW(TAG, "learned scale %s; save failed, will pair again after restart", addr);
  } else {
    ESP_LOGI(TAG, "paired with scale %s", addr);
  }
}

static int gap_event(struct ble_gap_event *event, void *arg);

static void fail_session(void) {
  uint16_t conn;
  lock_ble();
  conn = s_connected ? s_conn : BLE_HS_CONN_HANDLE_NONE;
  unlock_ble();
  if (conn != BLE_HS_CONN_HANDLE_NONE) {
    ble_gap_terminate(conn, BLE_ERR_REM_USER_CONN_TERM);
  } else {
    scan_start();
  }
}

static void scan_start(void) {
  uint8_t own;
  struct ble_gap_disc_params p = {0};
  int                        rc;

  if (!g_relay.configured) {
    return;
  }
  lock_ble();
  if (s_connected) {
    unlock_ble();
    return;
  }
  unlock_ble();
  if (ble_gap_disc_active()) {
    return;
  }
  if (ble_hs_id_infer_auto(0, &own) != 0) {
    ESP_LOGW(TAG, "no address for scan");
    return;
  }
  p.filter_duplicates = 0;
  lock_ble();
  /* Active scanning also returns scan responses, which may carry the name. */
  p.passive = s_scale_addr[0] != 0;
  unlock_ble();
  rc                  = ble_gap_disc(own, BLE_HS_FOREVER, &p, gap_event, NULL);
  if (rc != 0 && rc != BLE_HS_EALREADY) {
    ESP_LOGW(TAG, "scan start %d", rc);
  }
}

static int on_write(uint16_t conn_handle, const struct ble_gatt_error *error,
                    struct ble_gatt_attr *attr, void *arg) {
  uint32_t epoch = (uint32_t)(uintptr_t)arg;
  (void)attr;
  if (!s_ack_active || epoch != s_ack_request.epoch || epoch != s_epoch ||
      conn_handle != s_conn) {
    return 0;
  }
  s_ack_active = 0;
  if (!error || error->status != 0) {
    fail_session();
  } else if (s_ack_request.disconnect_after) {
    ble_gap_terminate(conn_handle, BLE_ERR_REM_USER_CONN_TERM);
  } else {
    ble_npl_eventq_put(nimble_port_get_dflt_eventq(), &s_ack_event);
  }
  return 0;
}

/* GATT writes run on the host task: a connection cannot change between checking
 * its epoch and submitting an ACK. Only the final ACK's completion disconnects. */
static void pump_acks(struct ble_npl_event *event) {
  (void)event;
  if (s_ack_active) {
    return;
  }
  while (xQueueReceive(s_ack_requests, &s_ack_request, 0) == pdTRUE) {
    packet_t packet = {.sequence = s_ack_request.sequence, .unit = s_ack_request.unit};
    uint8_t  frame[FRAME_MAX];
    int      length;
    int      rc;
    if (!s_connected || s_ack_request.epoch != s_epoch || !s_ffb1) {
      continue;
    }
    length = acknowledge(&packet, s_ack_seq++, frame);
    if (length <= 0) {
      continue;
    }
    s_ack_active = 1;
    rc = ble_gattc_write_flat(s_conn, s_ffb1, frame, length, on_write,
                             (void *)(uintptr_t)s_epoch);
    if (rc == 0) {
      return;
    }
    s_ack_active = 0;
    ESP_LOGW(TAG, "ack write %d", rc);
  }
}

static int on_subscribe(uint16_t conn_handle, const struct ble_gatt_error *error,
                        struct ble_gatt_attr *attr, void *arg) {
  uint32_t epoch = (uint32_t)(uintptr_t)arg;
  (void)attr;
  if (epoch == s_epoch && conn_handle == s_conn && (!error || error->status != 0)) {
    ESP_LOGW(TAG, "subscription rejected");
    fail_session();
  }
  return 0;
}

static int subscribe(uint16_t handle, uint16_t value) {
  uint8_t  buf[2] = {(uint8_t)value, (uint8_t)(value >> 8)};
  uint16_t conn;
  uint32_t epoch;
  int      rc;

  lock_ble();
  conn  = s_conn;
  epoch = s_epoch;
  unlock_ble();
  rc = ble_gattc_write_flat(conn, handle, buf, 2, on_subscribe, (void *)(uintptr_t)epoch);
  if (rc != 0) {
    ESP_LOGW(TAG, "subscribe write %d", rc);
    fail_session();
    return rc;
  }
  return 0;
}

static int disc_chr(uint16_t conn_handle, const struct ble_gatt_error *error,
                    const struct ble_gatt_chr *chr, void *arg);

static int disc_dsc(uint16_t conn_handle, const struct ble_gatt_error *error,
                    uint16_t chr_val_handle, const struct ble_gatt_dsc *dsc, void *arg) {
  if (!s_connected || conn_handle != s_conn || (uint32_t)(uintptr_t)arg != s_epoch) {
    return BLE_HS_ENOTCONN;
  }
  if (error->status == BLE_HS_EDONE) {
    if (chr_val_handle == s_ffb2) {
      if (!s_ffb2_ccc) {
        ESP_LOGW(TAG, "missing notify CCC");
        fail_session();
        return 0;
      }
      int rc = ble_gattc_disc_all_dscs(conn_handle, s_ffb3, s_ffb3_end, disc_dsc, arg);
      if (rc != 0) {
        ESP_LOGW(TAG, "indicate descriptor discovery %d", rc);
        fail_session();
      }
      return 0;
    }
    if (!s_ffb3_ccc) {
      ESP_LOGW(TAG, "missing indicate CCC");
      fail_session();
      return 0;
    }
    if (subscribe(s_ffb2_ccc, 0x0001) == 0) {
      subscribe(s_ffb3_ccc, 0x0002);
    }
    return 0;
  }
  if (error->status != 0) {
    ESP_LOGW(TAG, "descriptor discovery %d", error->status);
    fail_session();
    return error->status;
  }
  if (dsc && scale_uuid16(&dsc->uuid.u) == 0x2902) {
    if (chr_val_handle == s_ffb2) {
      s_ffb2_ccc = dsc->handle;
    } else if (chr_val_handle == s_ffb3) {
      s_ffb3_ccc = dsc->handle;
    }
  }
  return 0;
}

static int disc_chr(uint16_t conn_handle, const struct ble_gatt_error *error,
                    const struct ble_gatt_chr *chr, void *arg) {
  uint16_t start;
  uint16_t end;
  int      rc;

  if (!s_connected || conn_handle != s_conn || (uint32_t)(uintptr_t)arg != s_epoch) {
    return BLE_HS_ENOTCONN;
  }
  if (error->status == BLE_HS_EDONE) {
    lock_ble();
    if (conn_handle != s_conn) {
      unlock_ble();
      return 0;
    }
    if (!s_ffb1 || !s_ffb2 || !s_ffb3 || !s_svc_end) {
      unlock_ble();
      ESP_LOGW(TAG, "FFB0 characteristics incomplete");
      fail_session();
      return 0;
    }
    if (!s_ffb2_end) {
      s_ffb2_end = s_svc_end;
    }
    if (!s_ffb3_end) {
      s_ffb3_end = s_svc_end;
    }
    start = s_ffb2;
    end   = s_ffb2_end;
    unlock_ble();
    rc = ble_gattc_disc_all_dscs(conn_handle, start, end, disc_dsc, arg);
    if (rc != 0) {
      ESP_LOGW(TAG, "dsc disc start %d", rc);
      fail_session();
    }
    return 0;
  }
  if (error->status != 0) {
    ESP_LOGW(TAG, "chr disc %d", error->status);
    fail_session();
    return error->status;
  }
  if (!chr) {
    return 0;
  }
  lock_ble();
  if (conn_handle != s_conn) {
    unlock_ble();
    return BLE_HS_ENOTCONN;
  }
  /* Discovery is in handle order. A descriptor range ends immediately before
   * the next characteristic declaration, not at the end of the service. */
  if (s_ffb2 && !s_ffb2_end && chr->def_handle > s_ffb2) {
    s_ffb2_end = chr->def_handle - 1;
  }
  if (s_ffb3 && !s_ffb3_end && chr->def_handle > s_ffb3) {
    s_ffb3_end = chr->def_handle - 1;
  }
  {
    uint16_t u = scale_uuid16(&chr->uuid.u);
    if (u == 0xFFB1) {
      s_ffb1 = chr->val_handle;
    } else if (u == 0xFFB2) {
      s_ffb2 = chr->val_handle;
    } else if (u == 0xFFB3) {
      s_ffb3 = chr->val_handle;
    }
  }
  unlock_ble();
  return 0;
}

static int disc_svc(uint16_t conn_handle, const struct ble_gatt_error *error,
                    const struct ble_gatt_svc *svc, void *arg) {
  int      rc;
  uint16_t start;
  uint16_t end;

  if (!s_connected || conn_handle != s_conn || (uint32_t)(uintptr_t)arg != s_epoch) {
    return BLE_HS_ENOTCONN;
  }
  if (error->status == BLE_HS_EDONE) {
    lock_ble();
    if (conn_handle != s_conn) {
      unlock_ble();
      return 0;
    }
    if (!s_have_svc) {
      unlock_ble();
      ESP_LOGW(TAG, "no FFB0 service");
      fail_session();
      return 0;
    }
    start = s_svc_start;
    end   = s_svc_end;
    unlock_ble();
    rc = ble_gattc_disc_all_chrs(conn_handle, start, end, disc_chr, arg);
    if (rc != 0) {
      ESP_LOGW(TAG, "chr disc start %d", rc);
      fail_session();
    }
    return 0;
  }
  if (error->status != 0) {
    ESP_LOGW(TAG, "svc disc %d", error->status);
    fail_session();
    return error->status;
  }
  if (!svc || scale_uuid16(&svc->uuid.u) != 0xFFB0) {
    return 0;
  }
  lock_ble();
  if (conn_handle != s_conn) {
    unlock_ble();
    return BLE_HS_ENOTCONN;
  }
  s_have_svc  = 1;
  s_svc_start = svc->start_handle;
  s_svc_end   = svc->end_handle;
  unlock_ble();
  return 0;
}

static int gap_event(struct ble_gap_event *event, void *arg) {
  (void)arg;
  switch (event->type) {
  case BLE_GAP_EVENT_DISC: {
    uint8_t own;
    int     rc;
    lock_ble();
    if (!g_relay.configured || s_connected || !scale_match(&event->disc)) {
      unlock_ble();
      return 0;
    }
    unlock_ble();
    ble_gap_disc_cancel();
    if (ble_hs_id_infer_auto(0, &own) != 0) {
      scan_start();
      return 0;
    }
    rc = ble_gap_connect(own, &event->disc.addr, 30000, NULL, gap_event, NULL);
    if (rc != 0) {
      ESP_LOGW(TAG, "connect %d", rc);
      scan_start();
    }
    return 0;
  }
  case BLE_GAP_EVENT_DISC_COMPLETE:
    lock_ble();
    if (!s_connected) {
      unlock_ble();
      scan_start();
    } else {
      unlock_ble();
    }
    return 0;
  case BLE_GAP_EVENT_CONNECT:
    if (event->connect.status != 0) {
      lock_ble();
      s_connected = 0;
      s_epoch++;
      clear_session_locked();
      unlock_ble();
      queue_reset();
      scan_start();
      return 0;
    }
    lock_ble();
    s_connected = 1;
    s_conn      = event->connect.conn_handle;
    {
      struct ble_gap_conn_desc desc;
      memset(&s_peer, 0, sizeof(s_peer));
      if (ble_gap_conn_find(s_conn, &desc) == 0) {
        s_peer = desc.peer_id_addr;
      }
    }
    s_epoch++;
    clear_session_locked();
    unlock_ble();
    queue_reset();
    {
      /* Find-by-UUID sends the requested width verbatim; FFB0 is 128-bit here. */
      int rc = ble_gattc_disc_all_svcs(event->connect.conn_handle,
                                      disc_svc, (void *)(uintptr_t)s_epoch);
      if (rc != 0) {
        ESP_LOGW(TAG, "svc disc start %d", rc);
        fail_session();
      }
    }
    return 0;
  case BLE_GAP_EVENT_DISCONNECT:
    lock_ble();
    s_connected = 0;
    s_epoch++;
    clear_session_locked();
    unlock_ble();
    queue_reset();
    scan_start();
    return 0;
  case BLE_GAP_EVENT_NOTIFY_RX: {
    ble_frame_msg_t msg;
    int             len;
    uint16_t        conn;
    uint16_t        ffb2;
    uint16_t        ffb3;

    lock_ble();
    conn = s_conn;
    ffb2 = s_ffb2;
    ffb3 = s_ffb3;
    msg.epoch = s_epoch;
    if (!s_connected || event->notify_rx.conn_handle != conn) {
      unlock_ble();
      return 0;
    }
    unlock_ble();
    if (event->notify_rx.attr_handle != ffb2 && event->notify_rx.attr_handle != ffb3) {
      return 0;
    }
    len = OS_MBUF_PKTLEN(event->notify_rx.om);
    if (len <= 0 || len > FRAME_MAX) {
      return 0;
    }
    os_mbuf_copydata(event->notify_rx.om, 0, len, msg.data);
    msg.len  = (uint16_t)len;
    msg.attr = event->notify_rx.attr_handle;
    xQueueSend(g_ble_frames, &msg, 0);
    return 0;
  }
  default:
    return 0;
  }
}

static void write_ack(const packet_t *packet, int disconnect_after, uint32_t epoch) {
  ack_request_t request = {
    .disconnect_after = disconnect_after,
    .epoch            = epoch,
    .sequence         = packet->sequence,
    .unit             = packet->unit,
  };
  if (xQueueSend(s_ack_requests, &request, 0) == pdTRUE) {
    ble_npl_eventq_put(nimble_port_get_dflt_eventq(), &s_ack_event);
  }
}

static void host_task(void *param) {
  (void)param;
  nimble_port_run();
  nimble_port_freertos_deinit();
}

static void on_sync(void) {
  ble_hs_util_ensure_addr(0);
  if (g_relay.configured) {
    scan_start();
  }
}

static void on_reset(int reason) {
  ESP_LOGW(TAG, "reset %d", reason);
  lock_ble();
  s_connected = 0;
  s_epoch++;
  clear_session_locked();
  unlock_ble();
  queue_reset();
}

static void ble_work(void *arg) {
  static frame_assembler_t notify_as;
  static frame_assembler_t indicate_as;
  static packet_decoder_t decoder;
  (void)arg;
  frame_assembler_init(&notify_as);
  frame_assembler_init(&indicate_as);
  packet_decoder_init(&decoder);
  for (;;) {
    ble_frame_msg_t msg;
    uint16_t        ffb3;
    uint32_t        epoch;

    if (xQueueReceive(g_ble_frames, &msg, portMAX_DELAY) != pdTRUE) {
      continue;
    }
    if (msg.attr == RESET_ATTR) {
      frame_assembler_init(&notify_as);
      frame_assembler_init(&indicate_as);
      packet_decoder_init(&decoder);
      continue;
    }
    lock_ble();
    ffb3  = s_ffb3;
    epoch = msg.epoch;
    if (!s_connected || epoch != s_epoch) {
      unlock_ble();
      continue;
    }
    unlock_ble();
    {
      frame_assembler_t *as = msg.attr == ffb3 ? &indicate_as : &notify_as;
      packet_t           packet;
      int                r = frame_assembler_add(as, msg.data, msg.len, &packet);
      if (r != 1) {
        continue;
      }
      {
        decoded_t decoded;
        int       released = 0;
        if (packet_decoder_feed(&decoder, &packet, &decoded, &released) != 0) {
          continue;
        }
        if (released && decoded.type == PKT_DEVICE_INFO) {
          learn_scale();
          write_ack(&packet, 0, epoch);
          {
            decoded_t extra;
            packet_t  pending;
            while (packet_decoder_flush(&decoder, &pending, &extra)) {
              int acked = 0;
              relay_apply_measurement(&pending, &decoder.device_info, &extra, &acked);
              if (acked) {
                write_ack(&pending, 1, epoch);
              }
            }
          }
          continue;
        }
        if (released) {
          int acked = 0;
          relay_apply_measurement(&packet, &decoder.device_info, &decoded, &acked);
          if (acked) {
            write_ack(&packet, 1, epoch);
          }
        }
      }
    }
  }
}

void ble_scale_start(void) {
  if (!g_relay.configured) {
    return;
  }
  memcpy(s_scale_addr, g_relay.cfg.scale_address, sizeof(s_scale_addr));
  s_ble_lock     = xSemaphoreCreateMutex();
  s_ack_requests = xQueueCreate(PACKET_PENDING + 1, sizeof(ack_request_t));
  ESP_ERROR_CHECK(s_ble_lock && s_ack_requests ? ESP_OK : ESP_ERR_NO_MEM);
  ESP_ERROR_CHECK(nimble_port_init());
  ble_npl_event_init(&s_ack_event, pump_acks, NULL);
  ble_hs_cfg.sync_cb  = on_sync;
  ble_hs_cfg.reset_cb = on_reset;
  ble_svc_gap_device_name_set("renpho-relay");
  ESP_ERROR_CHECK(xTaskCreate(ble_work, "blew", 8192, NULL, 8, NULL) == pdPASS
                   ? ESP_OK : ESP_ERR_NO_MEM);
  nimble_port_freertos_init(host_task);
}

void relay_apply_measurement(const packet_t *packet, const packet_t *device_info,
                             const decoded_t *decoded, int *acked) {
  char             event_id[65];
  enqueue_result_t enq;
  static outbox_t  snap;

  *acked = 0;
  if (decoded->type != PKT_MEASUREMENT) {
    return;
  }
  if (!decoded->has_weight || decoded->weight_g == 0) {
    return;
  }
  xSemaphoreTake(g_lock, portMAX_DELAY);
  snap = g_outbox;
  enq  = outbox_enqueue(&g_outbox, packet, device_info, decoded->weight_g, event_id);
  if (enq == ENQUEUE_NEW || enq == ENQUEUE_ENRICHED) {
    if (store_save_outbox() != ESP_OK) {
      g_outbox = snap;
      xSemaphoreGive(g_lock);
      return;
    }
    g_relay.ui = UI_QUEUED;
    *acked     = 1;
  } else if (enq == ENQUEUE_DUP) {
    *acked = 1;
  }
  xSemaphoreGive(g_lock);
  if (*acked) {
    board_lcd_activity();
  }
}
