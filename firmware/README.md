# Relay firmware

The relay operates on the Waveshare ESP32-S3-LCD-1.47 board.
The specified scale is the RENPHO R-MSC01.
Other scales and the 1.47B board are not verified.
The [project guide](../README.md) defines the terms in this document.

The relay saves weight and original scale packets in board flash.
It sends measurements to your HTTP receiver.
The relay has no clock. The receiver records the time of each measurement.
It shows weight in pounds to one decimal place, with kilograms below.
It does not calculate or show body-composition estimates.

## Equipment and software

- Waveshare ESP32-S3-LCD-1.47 with 16 MB flash and octal PSRAM.
- RENPHO R-MSC01 scale.
- USB data cable.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) with Python 3.12 or a subsequent version.
- Only to compile the firmware yourself: [ESP-IDF v5.5.2](https://docs.espressif.com/projects/esp-idf/en/v5.5.2/esp32s3/get-started/index.html).

The [web installer](https://snrogers.github.io/renpho-esp32-relay/) does all the steps in this guide from Chrome or Edge, without these tools.
- A 2.4 GHz Wi-Fi network that can connect to the receiver.
- A receiver with this [HTTP interface](#receiver-interface), such as the [reference receiver](../README.md#reference-receiver).

The scale uses BLE.
It does not connect to Wi-Fi.
The receiver does not have to use Wi-Fi.

The Python program must operate on the computer that has the USB device.
Under WSL, Windows owns USB.
From WSL, use `./flash.sh` instead of `uv run ... firmware/flash.py`, with the same arguments.
It runs the tool with Windows `uv.exe`, found on `PATH` or set in `UV_EXE`, and converts `--config` and `--build` paths.

## Get the firmware

Use a compiled release, or compile the firmware yourself.

To use a release:

1. Download `renpho-relay-firmware-VERSION.zip` from the [GitHub releases](https://github.com/snrogers/renpho-esp32-relay/releases).
2. Extract the archive.
3. In the commands in this guide, add `--build EXTRACTED_DIR` after the subcommand.
   `EXTRACTED_DIR` is the `renpho-relay-firmware-VERSION` directory from the archive.

To compile the firmware:

1. Install ESP-IDF v5.5.2 as specified in its installation guide.
2. Activate the ESP-IDF environment for your terminal.
3. Open the repository root directory.
4. Compile the firmware:

   ```sh
   idf.py -C firmware -DIDF_TARGET=esp32s3 build
   ```

5. Make sure that `firmware/build/flasher_args.json` exists.

Compilation does not use the board.
The defaults select 16 MB flash, octal PSRAM at 80 MHz, and USB Serial/JTAG.
The flash tool reads image addresses from `flasher_args.json`.

## Make a private configuration file

**CAUTION:** The configuration contains your Wi-Fi password.
Keep the file outside the repository.
Do not put the password in a command argument or public issue.
Flash backups can also contain this password and measurement data.

1. Make a private directory outside the repository.
2. Save this JSON as `relay-config.json` in that directory:

   ```json
   {
     "deviceId":     "example-relay-1",
     "receiverUrl":  "http://192.0.2.10:8080",
     "wifiSsid":     "example-wlan",
     "wifiPassword": "example-passphrase"
   }
   ```

3. Replace the example values with your configuration.
4. Keep the full path to the JSON file for subsequent commands.

These values are examples, not a working receiver.
`192.0.2.10` is a reserved documentation address.
All fields must be strings.
Only `wifiPassword` and `scaleAddress` can be empty.

### Scale pairing

Without `scaleAddress`, the relay pairs with the first scale that it finds.
It looks for the Bluetooth name `R-MSC01`.
It keeps the address after the scale sends a valid device-information packet.
The `status` command shows that address in `scaleAddress`.

If more than one R-MSC01 is near the relay, set `scaleAddress` to the address of your scale.
To pair again with a different scale, configure the relay without `scaleAddress`.
The tool accepts only the fields in the table and `command`.
It ignores `command`.

| Field          | Maximum length  | Format                                            |
| -------------- | --------------- | ------------------------------------------------- |
| `deviceId`     | 128 UTF-8 bytes | ASCII letters, digits, `.`, `_`, `:`, or `-`      |
| `receiverUrl`  | 256 UTF-8 bytes | Base URL with `http` or `https`                   |
| `scaleAddress` | 17 bytes        | Optional BLE address, such as `AA:BB:CC:DD:EE:FF` |
| `wifiSsid`     | 32 UTF-8 bytes  | Wi-Fi network name                                |
| `wifiPassword` | 64 UTF-8 bytes  | Wi-Fi password, or an empty string                |

The URL must not contain credentials, a query, or a fragment.
The firmware adds `/api/scale-readings` to the base URL.
Do not include that endpoint in `receiverUrl`.

## Save the current firmware

**CAUTION:** Firmware installation replaces the board's program.
Save a complete flash backup before the first installation.
Keep the backup outside the repository.
Do not use an erase command to install or update this relay.

In these commands, `PORT` means the serial port for your board.
`BACKUP_BIN` means the full path for a new backup file outside the repository.
Examples of serial ports are `COM7` on Windows and `/dev/ttyACM0` on Linux.

1. Connect the board with a USB data cable.
2. Close programs that use its serial port.
3. List the serial ports:

   ```sh
   uv run --python 3.12 --script firmware/flash.py ports
   ```

4. Identify the Espressif USB Serial/JTAG port.
5. Replace `PORT` and `BACKUP_BIN` in this command.
6. Copy all 16 MB of flash:

   ```sh
   uv run --python 3.12 --with esptool==5.4.0 python -m esptool --chip esp32s3 --port PORT read-flash 0 0x1000000 BACKUP_BIN
   ```

7. Make sure that the backup file contains 16,777,216 bytes.

## Guided setup

The `setup` command does the steps in this guide in one session.
It asks for the settings, so you do not have to make a configuration file.

1. Disconnect the phone app from the scale.
2. Connect the board with a USB data cable.
3. Start the guided setup:

   ```sh
   uv run --python 3.12 --script firmware/flash.py setup
   ```

4. Answer the questions.
   The tool does not show the Wi-Fi password while you type it.
5. Step onto the scale when the tool tells you to.

The tool can save a flash backup and a private settings file in your home directory.
It finds the board port when only one Espressif port exists. If not, it asks you to select one.
It stops if the relay does not connect to Wi-Fi in 60 seconds.

## Install and configure

Start each command from the repository root.
`CONFIG_JSON` means the full path to your private JSON file.
Replace `CONFIG_JSON` and `PORT` before you use a command.
Put quotation marks around paths that contain spaces.

If a different computer compiled the firmware, make its build directory available to the USB computer.
Use `--build BUILD_DIR` after the subcommand to select that directory.
The default build directory is `firmware/build`.

1. Disconnect the phone app from the scale.
2. Check the build files and configuration without the board:

   ```sh
   uv run --python 3.12 --script firmware/flash.py inspect --config CONFIG_JSON
   ```

3. Make sure that the output contains `config` with the value `valid`.
4. Complete the [flash backup procedure](#save-the-current-firmware).
5. Install and configure the relay:

   ```sh
   uv run --python 3.12 --script firmware/flash.py flash --config CONFIG_JSON --port PORT
   ```

6. Read the board status after it restarts:

   ```sh
   uv run --python 3.12 --script firmware/flash.py status --port PORT
   ```

7. Make sure that `configured` and `storageReady` are `true`.
8. Make sure that `wifiConnected` becomes `true`.
9. Activate the scale. Then make sure that `status` shows the scale address in `scaleAddress`.

The flash tool uses esptool 5.4.0 and pyserial 3.5.
It writes the images from the build metadata, then sends the configuration through USB.
Configuration changes restart the board but keep the outbox.
The tool hides `wifiPassword` in its output.
The `inspect` command shows `wifiPasswordSet`, not the password.

To change configuration without a firmware update, use this command:

```sh
uv run --python 3.12 --script firmware/flash.py configure --config CONFIG_JSON --port PORT
```

Options follow the subcommand.
`--timeout` changes the USB event timeout from its default of 30 seconds.
An explicit `--port` is necessary unless the computer finds only one Espressif USB Serial/JTAG port.
The console operates at 115200 baud.

## Measurement storage

The relay gets device information and a final measurement in the same BLE connection.
It saves the two complete packets before it sends the final measurement ACK.
A stored duplicate also gets an ACK.
The device-information ACK is a separate operation.

The outbox uses a separate NVS partition in flash.
NVS means nonvolatile storage.
The outbox has 16 slots and survives a restart.
The relay can replace delivered records, but not undelivered records.
If all 16 slots hold undelivered records, the relay does not accept or acknowledge a new measurement.

The first startup converts records from previous outbox formats.
This conversion keeps their identifiers, packets, and delivery states.
It removes the stored capture times.
Records that previous firmware kept without a time become ready for delivery.
The relay can send these records without packet data.
If a matching packet arrives, the relay can add it and send that record again.

The relay does not keep a clock or send a measurement time.
The receiver must record the time when it gets a new measurement.
A measurement that waited in the outbox gets the time of its delivery, not of its capture.
A repeated request for the same `eventId` must not change the recorded time.
The original measurement packet stays in `scaleMeasurement` for receivers that decode it.

## Receiver interface

The repository includes a [reference receiver](../README.md#reference-receiver) that uses this interface.
The relay sends no `Authorization` header or client certificate.
Use a receiver and network that you control.
Plain HTTP does not encrypt the measurement.
For HTTPS, use a server certificate that the ESP-IDF certificate bundle accepts.

### Request

The relay sends `POST {receiverUrl}/api/scale-readings` with `Content-Type: application/json`.
The request timeout is 8 seconds.
The interval between retries starts at 2 seconds and doubles to 64 seconds.
A saved success resets the interval to 2 seconds.

| Field              | Content                                                                    |
| ------------------ | -------------------------------------------------------------------------- |
| `deviceId`         | Configured relay identifier                                                |
| `eventId`          | SHA-256 of the measurement payload, as 64 lowercase hexadecimal characters |
| `weightGrams`      | Unsigned weight from the scale packet, in grams                            |
| `scaleMeasurement` | Original packet data, when available                                       |

Measurements with the same payload have the same `eventId`.
Only the measurement payload is part of the hash.
The receiver must prevent duplicate records when it gets repeated requests.
It must also accept new packet data for an existing weight-only record.

`scaleMeasurement` has these fields:

| Field                   | Content                                                                  |
| ----------------------- | ------------------------------------------------------------------------ |
| `deviceInfoPayloadHex`  | Device-information payload as hexadecimal text                           |
| `measurementPayloadHex` | Measurement payload as hexadecimal text                                  |
| `sequence`              | Measurement sequence number, from 0 through 255                          |
| `unit`                  | Measurement transport unit value, from 0 through 7                       |
| `rawPackets`            | Two packet objects, with device information first and measurement second |

Each packet object has `payloadHex`, `sequence`, and `unit`.
Each original payload has a maximum length of 512 bytes.
The hexadecimal text represents complete payloads, not individual BLE notification frames.
These values use the scale protocol units, not the LCD display units.

### Response

A successful response has HTTP status `200` and one JSON object.
The maximum response body length is 511 bytes.
The object must contain these strings:

| Field     | Accepted content                         |
| --------- | ---------------------------------------- |
| `eventId` | Same identifier as the request           |
| `status`  | `recorded`, `duplicate`, or `superseded` |

The relay ignores other keys.
An incorrect status, mismatched identifier, invalid JSON, or body larger than 511 bytes keeps the record in the outbox.
The relay saves the delivered state to flash after an accepted response.
If the relay cannot save that state, the record stays queued.

## Display and fault checks

The display states include `USB setup`, `Pairing`, `Listening`, `Queued`, `Delivered`, and `Storage error`.
The [main guide](../README.md#relay-screens) shows an image of each state.
`Pairing` means that the relay has no scale address. It tells you to step onto the scale, and it does not show a stored weight.
`Storage error` means that the relay cannot save measurements. It does not show a stored weight. Use the `Storage error` procedure in the table.
`Delivered` means the receiver accepted the record.
It does not mean that the receiver calculated body composition.
The relay shows `Delivered` for 30 seconds. Then it shows `Listening` and waits for the next measurement.
`Listening` does not show a stored weight. `Queued` shows the weight until the receiver accepts the record.

| Problem                 | Procedure                                                                                              |
| ----------------------- | ------------------------------------------------------------------------------------------------------ |
| No serial port          | Check the USB data cable and the computer that owns the USB device.                                    |
| Port access failure     | Close other serial tools. Check the selected port.                                                     |
| USB timeout after reset | Check the port again. Use `status` again with `--timeout 60`.                                          |
| No scale connection     | Activate the scale. Disconnect the phone app. Stop the computer recorder. Check `scaleAddress`.        |
| Wi-Fi disconnected      | Check the SSID, password, and 2.4 GHz network.                                                         |
| Outbox full             | Restore delivery to the receiver. Do not erase the outbox to make space.                               |
| Repeated uploads        | Check the receiver response against the interface above.                                               |
| `Storage error`         | Stop measurement use. Keep a flash backup for investigation. Do not erase NVS.                         |

## Host software checks

The host checks examine protocol decoding, storage, response parsing, and display rendering without a board.
A C compiler and Make are necessary.

```sh
make -C firmware/host
firmware/host/verify
```

Successful output ends with `ok`.
These checks do not prove USB, BLE, Wi-Fi, or physical display operation.
