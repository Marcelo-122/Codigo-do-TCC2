CC = g++
CFLAGS = -I/usr/include/opencv4 -I/usr/include/qt6 -I/usr/include/qt6/QtWidgets
LDLIBS = -lopencv_core -lopencv_imgproc -lopencv_highgui -lopencv_imgcodecs -lQt6Widgets -lQt6Core -lQt6Gui
TARGET = programa

all: clean $(TARGET)
	./$(TARGET)
$(TARGET): main.cpp
	$(CC) main.cpp -o $(TARGET) $(CFLAGS) $(LDLIBS)
clean:
	rm -f $(TARGET) *.o