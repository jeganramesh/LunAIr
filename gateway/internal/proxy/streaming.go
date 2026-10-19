package proxy

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

// SSE content types that must never be buffered.
var sseContentTypes = []string{"text/event-stream"}

// IsStreaming reports whether a response body should be flushed per chunk.
func IsStreaming(contentType string) bool {
	contentType = strings.ToLower(contentType)
	for _, ct := range sseContentTypes {
		if strings.Contains(contentType, ct) {
			return true
		}
	}
	return false
}

// SSEWriter guarantees Flush() reaches the underlying writer so Gin handlers
// can emit server-sent events incrementally.
type SSEWriter struct {
	gin.ResponseWriter
}

func (w SSEWriter) Write(b []byte) (int, error) {
	n, err := w.ResponseWriter.Write(b)
	w.ResponseWriter.Flush()
	return n, err
}

// Flush sends any buffered data to the client immediately.
func (w SSEWriter) Flush() {
	w.ResponseWriter.Flush()
}

// StreamFlush swaps the Gin writer for one that flushes after every write.
func StreamFlush() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Writer = SSEWriter{ResponseWriter: c.Writer}
		c.Next()
	}
}

// WriteSSEChunk writes one server-sent event and flushes it.
func WriteSSEChunk(c *gin.Context, chunk []byte) error {
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")

	if _, err := c.Writer.Write(chunk); err != nil {
		return err
	}
	if flusher, ok := c.Writer.(http.Flusher); ok {
		flusher.Flush()
	}
	return nil
}
