package tests

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/lunair/lunair/gateway/internal/config"
	"github.com/lunair/lunair/gateway/internal/health"
	"github.com/lunair/lunair/gateway/internal/proxy"
)

func testConfig(fastapiURL string) config.Config {
	return config.Config{
		Port:        "0",
		FastAPIURL:  fastapiURL,
		RedisURL:    "redis://127.0.0.1:6379/0",
		GatewayMode: config.ModeGo,
	}
}

func TestReverseProxyInjectsTrustedHeaders(t *testing.T) {
	var gotVerified, gotKeyID, gotGateway string

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotVerified = r.Header.Get(proxy.HeaderVerified)
		gotKeyID = r.Header.Get(proxy.HeaderKeyID)
		gotGateway = r.Header.Get(proxy.HeaderGateway)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"ok":true}`))
	}))
	defer upstream.Close()

	handler, err := proxy.NewHandler(testConfig(upstream.URL))
	if err != nil {
		t.Fatalf("NewHandler: %v", err)
	}

	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if gotVerified != "true" {
		t.Errorf("%s = %q, want true", proxy.HeaderVerified, gotVerified)
	}
	if gotKeyID != "gateway-verified-key" {
		t.Errorf("%s = %q, want gateway-verified-key", proxy.HeaderKeyID, gotKeyID)
	}
	if gotGateway != config.ModeGo {
		t.Errorf("%s = %q, want %s", proxy.HeaderGateway, gotGateway, config.ModeGo)
	}
}

func TestReverseProxyPreservesClientKeyID(t *testing.T) {
	var gotKeyID string

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotKeyID = r.Header.Get(proxy.HeaderKeyID)
		w.WriteHeader(http.StatusOK)
	}))
	defer upstream.Close()

	handler, err := proxy.NewHandler(testConfig(upstream.URL))
	if err != nil {
		t.Fatalf("NewHandler: %v", err)
	}

	req := httptest.NewRequest(http.MethodGet, "/v1/models", nil)
	req.Header.Set(proxy.HeaderKeyID, "key_from_client")
	handler.ServeHTTP(httptest.NewRecorder(), req)

	if gotKeyID != "key_from_client" {
		t.Errorf("%s = %q, want key_from_client", proxy.HeaderKeyID, gotKeyID)
	}
}

func TestReverseProxyUpstreamDownReturnsBadGateway(t *testing.T) {
	handler, err := proxy.NewHandler(testConfig("http://127.0.0.1:1"))
	if err != nil {
		t.Fatalf("NewHandler: %v", err)
	}

	req := httptest.NewRequest(http.MethodGet, "/v1/models", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want 502", rec.Code)
	}
}

func TestIsStreaming(t *testing.T) {
	cases := map[string]bool{
		"text/event-stream":                true,
		"text/event-stream; charset=utf-8": true,
		"application/json":                 false,
		"text/plain":                       false,
	}
	for contentType, want := range cases {
		if got := proxy.IsStreaming(contentType); got != want {
			t.Errorf("IsStreaming(%q) = %v, want %v", contentType, got, want)
		}
	}
}

func TestHealthHandler(t *testing.T) {
	h := health.NewHandler(testConfig("http://fastapi:8000"))

	rec := httptest.NewRecorder()
	c, _ := newGinContext(rec)
	h.Health(c)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}

	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode body: %v", err)
	}
	if body["status"] != "ok" {
		t.Errorf("status field = %v, want ok", body["status"])
	}
	if body["mode"] != config.ModeGo {
		t.Errorf("mode field = %v, want %s", body["mode"], config.ModeGo)
	}
}

func TestConfigIsGoMode(t *testing.T) {
	if testConfig("http://fastapi:8000").IsGoMode() != true {
		t.Error("mode go should be active")
	}

	fastAPIOnly := testConfig("http://fastapi:8000")
	fastAPIOnly.GatewayMode = config.ModeFastAPIOnly
	if fastAPIOnly.IsGoMode() {
		t.Error("mode fastapi_only should disable the gateway")
	}
}
