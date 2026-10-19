package config

import (
	"os"
	"strconv"
	"strings"
	"time"
)

const (
	ModeGo          = "go"
	ModeFastAPIOnly = "fastapi_only"
)

type Config struct {
	Port         string
	FastAPIURL   string
	RedisURL     string
	GatewayMode  string
	SharedSecret string
	ReadTimeout  time.Duration
	IdleTimeout  time.Duration
	AuthCacheTTL time.Duration
}

func Load() Config {
	fastapiURL := strings.TrimRight(env("FASTAPI_URL", "http://fastapi:8000"), "/")
	return Config{
		Port:         env("GATEWAY_PORT", "8080"),
		FastAPIURL:   fastapiURL,
		RedisURL:     env("REDIS_URL", "redis://redis:6379/0"),
		GatewayMode:  env("GATEWAY_MODE", ModeGo),
		SharedSecret: env("GATEWAY_SHARED_SECRET", ""),
		ReadTimeout:  envDuration("GATEWAY_READ_TIMEOUT_SECONDS", 60*time.Second),
		IdleTimeout:  envDuration("GATEWAY_IDLE_TIMEOUT_SECONDS", 120*time.Second),
		AuthCacheTTL: envDuration("GATEWAY_AUTH_CACHE_SECONDS", 60*time.Second),
	}
}

// ValidateURL is the core endpoint the gateway calls to resolve an API key.
func (c Config) ValidateURL() string {
	return c.FastAPIURL + "/internal/validate"
}

// IsGoMode reports whether the gateway is the active edge layer.
func (c Config) IsGoMode() bool {
	return c.GatewayMode != ModeFastAPIOnly
}

func env(key, fallback string) string {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		return v
	}
	return fallback
}

func envDuration(key string, fallback time.Duration) time.Duration {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		if seconds, err := strconv.Atoi(v); err == nil {
			return time.Duration(seconds) * time.Second
		}
	}
	return fallback
}
