TARGET = ocr_inference
CC = gcc
# CFLAGS = -Wall -Wextra -O2 -I/usr/local/include
CFLAGS = -Wall -Wextra -O2
# O flag -Wl,-rpath grava o caminho da biblioteca no próprio executável
# LDFLAGS = -L/usr/local/lib -Wl,-rpath,/usr/local/lib
LIBS = -ltensorflow -lm

SRCS = main.c

all: $(TARGET)

$(TARGET): $(SRCS)
# 	$(CC) $(CFLAGS) $(SRCS) -o $(TARGET) $(LDFLAGS) $(LIBS)
	$(CC) $(CFLAGS) $(SRCS) -o $(TARGET) $(LIBS)

clean:
	rm -f $(TARGET) img_*.jpg

.PHONY: all clean