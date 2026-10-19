package config

import (
	"os"
	"strconv"
	"strings"
)

const (
	ModeGo          = "go"
	ModeFastAPIOnly = "fastapi_only"
)

type Config struct {
	Port        string
	FastAPIURL  string
	RedisURL    string
	GatewayMode string
}

func Load() Config {
	return Config{
		Port:        env("GATEWAY_PORT", "8080"),
		FastAPIURL:  strings.TrimRight(env("FASTAPI_URL", "http://fastapi:8000"), "/"),
		RedisURL:    env("REDIS_URL", "redis://redis:6379/0"),
		GatewayMode: env("GATEWAY_MODE", ModeGo),
	}
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

func envInt(key string, fallback int) int {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		if parsed, err := strconv.Atoi(v); err == nil {
			return parsed
		}
	}
	return fallback
}
