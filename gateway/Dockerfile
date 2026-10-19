FROM golang:1.22-alpine AS builder

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -o /out/lunair-gateway ./cmd/lunair-gateway

FROM alpine:3.20

RUN apk add --no-cache ca-certificates tzdata

COPY --from=builder /out/lunair-gateway /usr/local/bin/lunair-gateway

ENV GATEWAY_PORT=8080 \
    GATEWAY_MODE=go \
    FASTAPI_URL=http://fastapi:8000

EXPOSE 8080

CMD ["/usr/local/bin/lunair-gateway"]
