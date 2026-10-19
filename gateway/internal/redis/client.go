package redisclient

import (
	"context"
	"fmt"
	"time"

	"github.com/redis/go-redis/v9"

	"github.com/lunair/lunair/gateway/pkg/logger"
)

// New builds a Redis client from REDIS_URL.
func New(redisURL string) (*redis.Client, error) {
	opts, err := redis.ParseURL(redisURL)
	if err != nil {
		return nil, fmt.Errorf("invalid REDIS_URL %q: %w", redisURL, err)
	}
	return redis.NewClient(opts), nil
}

// Ping verifies connectivity without blocking startup on failure.
func Ping(ctx context.Context, client *redis.Client) error {
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()

	if err := client.Ping(ctx).Err(); err != nil {
		return fmt.Errorf("redis ping failed: %w", err)
	}
	logger.Infof("redis connected")
	return nil
}
