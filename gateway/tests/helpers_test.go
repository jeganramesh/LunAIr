package tests

import (
	"net/http/httptest"

	"github.com/gin-gonic/gin"
)

// newGinContext builds a Gin test context for direct handler invocation.
func newGinContext(rec *httptest.ResponseRecorder) (*gin.Context, *gin.Engine) {
	gin.SetMode(gin.TestMode)
	c, _ := gin.CreateTestContext(rec)
	return c, nil
}
