FROM scratch
COPY --chmod=0555 jaeger-2.22.0-linux-amd64/jaeger /jaeger
EXPOSE 16686 4317 4318
ENTRYPOINT ["/jaeger"]
