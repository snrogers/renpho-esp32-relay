.RECIPEPREFIX := >
CC      = cc
CFLAGS  = -std=c11 -O2 -Wall -Wextra -I../core -D_GNU_SOURCE
CORE    = ../core/protocol.c ../core/outbox.c ../core/render.c ../core/sha256.c \
          ../core/http_parse.c ../core/config_validate.c ../core/usb_line.c
HEADERS = $(wildcard ../core/*.h)
TESTS   = verify.c verify_outbox_packets.c verify_upload_packets.c
.PHONY: all clean
all: verify
verify: $(TESTS) $(CORE) $(HEADERS)
>  $(CC) $(CFLAGS) -o $@ $(TESTS) $(CORE)
clean:
>  rm -f verify
