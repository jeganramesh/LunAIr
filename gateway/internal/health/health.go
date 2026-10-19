package health

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/lunair/lunair/gateway/internal/config"
)

type Handler struct {
	mode       string
	fastapiURL string
	startedAt  time.Time
}

func NewHandler(cfg config.Config) *Handler {
	return &Handler{
		mode:       cfg.GatewayMode,
		fastapiURL: cfg.FastAPIURL,
		startedAt:  time.Now(),
	}
}

func (h *Handler) Health(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status":      "ok",
		"component":   "gateway",
		"mode":        h.mode,
		"fastapi_url": h.fastapiURL,
		"uptime_s":    int(time.Since(h.startedAt).Seconds()),
	})
}
