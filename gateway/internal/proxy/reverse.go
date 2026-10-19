package proxy

import (
	"fmt"
	"net/http"
	"net/http/httputil"
	"net/url"
	"time"

	"github.com/lunair/lunair/gateway/internal/config"
	"github.com/lunair/lunair/gateway/pkg/logger"
)

// Trusted headers injected on every forwarded request so FastAPI can skip
// its own auth path (see app/src/lunair/core/trust.py).
const (
	HeaderVerified = "X-LUNAIR-Verified"
	HeaderKeyID    = "X-LUNAIR-Key-Id"
	HeaderGateway  = "X-LUNAIR-Gateway"
)

type Handler struct {
	proxy *httputil.ReverseProxy
}

func NewHandler(cfg config.Config) (*Handler, error) {
	target, err := url.Parse(cfg.FastAPIURL)
	if err != nil {
		return nil, fmt.Errorf("invalid FASTAPI_URL %q: %w", cfg.FastAPIURL, err)
	}

	rp := httputil.NewSingleHostReverseProxy(target)

	// httputil.DefaultTransport keeps only 2 idle connections per host. Under
	// concurrency that forces a fresh TCP dial to FastAPI for nearly every
	// forwarded request, which shows up as a fat p95/p99 tail. Size the pool
	// for the concurrency the gateway is expected to absorb.
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.MaxIdleConns = 256
	transport.MaxIdleConnsPerHost = 256
	transport.MaxConnsPerHost = 0 // unbounded; idle pool is the real limit
	transport.IdleConnTimeout = 90 * time.Second
	rp.Transport = transport

	// FlushInterval -1 keeps SSE chunks streaming instead of being buffered.
	rp.FlushInterval = -1

	rp.Director = func(req *http.Request) {
		req.URL.Scheme = target.Scheme
		req.URL.Host = target.Host
		req.Host = target.Host

		req.Header.Set(HeaderVerified, "true")
		if req.Header.Get(HeaderKeyID) == "" {
			req.Header.Set(HeaderKeyID, "gateway-verified-key")
		}
		req.Header.Set(HeaderGateway, cfg.GatewayMode)
	}

	rp.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		logger.Errorf("proxy error path=%s err=%v", r.URL.Path, err)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadGateway)
		_, _ = w.Write([]byte(`{"error":{"message":"upstream unavailable","type":"proxy_error"}}`))
	}

	return &Handler{proxy: rp}, nil
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	h.proxy.ServeHTTP(w, r)
}
