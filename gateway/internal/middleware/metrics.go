package middleware

import (
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

var (
	requestsTotal = promauto.NewCounterVec(
		prometheus.CounterOpts{
			Name: "lunair_gateway_requests_total",
			Help: "Total requests handled by the gateway, by method/path/status.",
		},
		[]string{"method", "path", "status"},
	)

	latencySeconds = promauto.NewHistogramVec(
		prometheus.HistogramOpts{
			Name:    "lunair_gateway_latency_seconds",
			Help:    "Gateway request latency in seconds.",
			Buckets: prometheus.DefBuckets,
		},
		[]string{"method", "path"},
	)
)

// Metrics records per-request counters and latency.
func Metrics() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		path := c.FullPath()
		if path == "" {
			path = "unmatched"
		}

		c.Next()

		status := strconv.Itoa(c.Writer.Status())
		requestsTotal.WithLabelValues(c.Request.Method, path, status).Inc()
		latencySeconds.WithLabelValues(c.Request.Method, path).Observe(time.Since(start).Seconds())
	}
}
