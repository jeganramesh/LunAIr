package main

import (
	"context"
	"errors"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/prometheus/client_golang/prometheus/promhttp"

	"github.com/lunair/lunair/gateway/internal/auth"
	"github.com/lunair/lunair/gateway/internal/config"
	"github.com/lunair/lunair/gateway/internal/health"
	"github.com/lunair/lunair/gateway/internal/middleware"
	"github.com/lunair/lunair/gateway/internal/proxy"
	redisclient "github.com/lunair/lunair/gateway/internal/redis"
	"github.com/lunair/lunair/gateway/pkg/logger"
)

func main() {
	cfg := config.Load()

	if !cfg.IsGoMode() {
		logger.Warnf("GATEWAY_MODE=%s — gateway will not forward traffic; hit FastAPI directly", cfg.GatewayMode)
	}
	if cfg.SharedSecret == "" {
		logger.Warnf("GATEWAY_SHARED_SECRET is unset — /v1 will return 503 until it is configured")
	}

	ctx := context.Background()
	rdb, err := redisclient.New(cfg.RedisURL)
	if err != nil {
		logger.Warnf("redis disabled: %v", err)
		rdb = nil
	} else if err := redisclient.Ping(ctx, rdb); err != nil {
		logger.Warnf("redis unavailable: %v", err)
	} else {
		defer func() { _ = rdb.Close() }()
	}

	proxyHandler, err := proxy.NewHandler(cfg)
	if err != nil {
		logger.Errorf("cannot build proxy: %v", err)
		os.Exit(1)
	}

	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery(), middleware.Metrics(), proxy.StreamFlush())

	r.GET("/health", health.NewHandler(cfg).Health)
	r.GET("/metrics", gin.WrapH(promhttp.Handler()))

	if cfg.IsGoMode() {
		// Authentication runs at the edge; the core then trusts the resolved
		// identity via the shared secret.
		r.Any("/v1/*path", auth.Authenticate(cfg, rdb), gin.WrapH(proxyHandler))
	} else {
		r.NoRoute(func(c *gin.Context) {
			c.JSON(http.StatusNotFound, gin.H{
				"error": gin.H{
					"message": "gateway is in fastapi_only mode; call FastAPI directly",
					"type":    "gateway_disabled",
				},
			})
		})
	}

	srv := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           r,
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       cfg.ReadTimeout,
		IdleTimeout:       cfg.IdleTimeout,
		// WriteTimeout stays 0: SSE responses stream for as long as the
		// upstream takes and must not be cut off.
	}

	go func() {
		logger.Infof("gateway listening port=%s upstream=%s mode=%s",
			cfg.Port, cfg.FastAPIURL, cfg.GatewayMode)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Errorf("gateway server error: %v", err)
			os.Exit(1)
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		logger.Errorf("graceful shutdown failed: %v", err)
	}
	logger.Infof("gateway stopped")
}
