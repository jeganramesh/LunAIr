package logger

import (
	"fmt"
	"log"
	"os"
)

var std = log.New(os.Stdout, "", log.LstdFlags|log.LUTC)

// Infof logs an operational message.
func Infof(format string, args ...any) {
	std.Printf("INFO  "+format, args...)
}

// Warnf logs a recoverable problem.
func Warnf(format string, args ...any) {
	std.Printf("WARN  "+format, args...)
}

// Errorf logs a failure.
func Errorf(format string, args ...any) {
	std.Printf("ERROR "+format, args...)
}

// KV builds a compact key=value pair for structured-ish log lines.
func KV(key string, value any) string {
	return key + "=" + fmt.Sprint(value)
}
