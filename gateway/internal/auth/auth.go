// Package auth authenticates callers at the edge.
//
// The gateway resolves the caller's API key *before* forwarding, so the core
// never has to trust a client-supplied identity header. Resolution calls the
// core's internal validate endpoint (which is itself gated on the shared
// secret) and caches the result in Redis for a short TTL.
package auth

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"

	"github.com/lunair/lunair/gateway/internal/config"
	"github.com/lunair/lunair/gateway/pkg/logger"
)

const (
	// ContextKeyID is the gin context key holding the resolved key id.
	ContextKeyID = "lunair_key_id"
	// HeaderKeyID is the header the proxy forwards the resolved key id in.
	HeaderKeyID = "X-LUNAIR-Key-Id"
	// HeaderGatewaySecret carries the shared secret on the validate call.
	HeaderGatewaySecret = "X-LUNAIR-Gateway-Secret"
)

// Authenticate returns middleware that rejects unauthenticated /v1 traffic.
func Authenticate(cfg config.Config, rdb *redis.Client) gin.HandlerFunc {
	client := &http.Client{Timeout: 5 * time.Second}

	return func(c *gin.Context) {
		if cfg.SharedSecret == "" {
			logger.Errorf("GATEWAY_SHARED_SECRET is not set — refusing to serve /v1")
			c.AbortWithStatusJSON(http.StatusServiceUnavailable, gin.H{
				"error": gin.H{
					"message": "gateway is not configured with a shared secret",
					"type":    "gateway_unconfigured",
				},
			})
			return
		}

		token := bearerToken(c.Request.Header.Get("Authorization"))
		if token == "" {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
				"error": gin.H{"message": "Missing Bearer API key", "type": "invalid_request_error"},
			})
			return
		}

		keyID, ok := lookupCached(c.Request.Context(), rdb, token)
		if !ok {
			resolved, err := validateRemote(c.Request.Context(), client, cfg, token)
			if err != nil {
				logger.Warnf("key validation failed: %v", err)
				c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
					"error": gin.H{"message": "Invalid API key", "type": "invalid_request_error"},
				})
				return
			}
			keyID = resolved
			cacheKeyID(c.Request.Context(), rdb, token, keyID, cfg.AuthCacheTTL)
		}

		// Hand the resolved identity to the proxy via a header it can trust.
		c.Request.Header.Set(HeaderKeyID, keyID)
		c.Set(ContextKeyID, keyID)
		c.Next()
	}
}

func bearerToken(header string) string {
	if strings.HasPrefix(header, "Bearer ") {
		return strings.TrimSpace(strings.TrimPrefix(header, "Bearer "))
	}
	return ""
}

func tokenHash(token string) string {
	sum := sha256.Sum256([]byte(token))
	return hex.EncodeToString(sum[:])
}

func cacheKey(token string) string {
	return "gw:auth:" + tokenHash(token)
}

func lookupCached(ctx context.Context, rdb *redis.Client, token string) (string, bool) {
	if rdb == nil {
		return "", false
	}
	val, err := rdb.Get(ctx, cacheKey(token)).Result()
	if err != nil || val == "" {
		return "", false
	}
	return val, true
}

func cacheKeyID(ctx context.Context, rdb *redis.Client, token, keyID string, ttl time.Duration) {
	if rdb == nil {
		return
	}
	_ = rdb.Set(ctx, cacheKey(token), keyID, ttl).Err()
}

type validateResponse struct {
	Valid bool   `json:"valid"`
	KeyID string `json:"key_id"`
}

func validateRemote(ctx context.Context, client *http.Client, cfg config.Config, token string) (string, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, cfg.ValidateURL(), bytes.NewReader([]byte("{}")))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set(HeaderGatewaySecret, cfg.SharedSecret)

	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode != http.StatusOK {
		_, _ = io.Copy(io.Discard, resp.Body)
		return "", &validationError{status: resp.StatusCode}
	}

	var parsed validateResponse
	if err := json.NewDecoder(resp.Body).Decode(&parsed); err != nil {
		return "", err
	}
	if !parsed.Valid || parsed.KeyID == "" {
		return "", &validationError{status: http.StatusUnauthorized}
	}
	return parsed.KeyID, nil
}

type validationError struct{ status int }

func (e *validationError) Error() string {
	return "validation rejected with status " + http.StatusText(e.status)
}
