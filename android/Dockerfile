# syntax=docker/dockerfile:1
# Build image for the newsagg Android app (Go + Drift framework)
#
# Produces newsapp.apk in /out/ when run with:
#   docker run --rm -v "$PWD/out:/out" newsagg-android
#
# Or to build interactively (with a connected adb device):
#   docker run --rm -it --privileged -v /dev/bus/usb:/dev/bus/usb newsagg-android bash

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# ── System packages ──────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Build essentials
    build-essential \
    cmake \
    ninja-build \
    git \
    curl \
    unzip \
    wget \
    file \
    # Java 17 (required by Gradle / Android build tools)
    openjdk-17-jdk-headless \
    # adb for device installs
    adb \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64

# ── Go 1.24 ──────────────────────────────────────────────────────────────────
ARG GO_VERSION=1.24.2
RUN curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz" \
    | tar -C /usr/local -xz
ENV PATH="/usr/local/go/bin:${PATH}"
ENV GOPATH=/go
ENV PATH="${GOPATH}/bin:${PATH}"

# ── Android SDK command-line tools ───────────────────────────────────────────
# Drift requires: compileSdk 34, minSdk 29, NDK 27, build-tools 34, Gradle 8.2
ARG ANDROID_SDK_ROOT=/opt/android-sdk
ARG CMDLINE_TOOLS_VERSION=14742923
ENV ANDROID_HOME=${ANDROID_SDK_ROOT}
ENV ANDROID_SDK_ROOT=${ANDROID_SDK_ROOT}
ENV PATH="${ANDROID_SDK_ROOT}/cmdline-tools/latest/bin:${ANDROID_SDK_ROOT}/platform-tools:${PATH}"

RUN mkdir -p ${ANDROID_SDK_ROOT}/cmdline-tools && \
    curl -fsSL \
        "https://dl.google.com/android/repository/commandlinetools-linux-${CMDLINE_TOOLS_VERSION}_latest.zip" \
        -o /tmp/cmdline-tools.zip && \
    unzip -q /tmp/cmdline-tools.zip -d /tmp/cmdline-tools-extract && \
    mv /tmp/cmdline-tools-extract/cmdline-tools ${ANDROID_SDK_ROOT}/cmdline-tools/latest && \
    rm -rf /tmp/cmdline-tools.zip /tmp/cmdline-tools-extract

# Accept licences and install required SDK components
RUN yes | sdkmanager --licenses > /dev/null 2>&1 || true && \
    sdkmanager \
        "platform-tools" \
        "platforms;android-34" \
        "build-tools;34.0.0" \
        "ndk;27.0.12077973" \
        "cmake;3.22.1"

ENV ANDROID_NDK_HOME=${ANDROID_SDK_ROOT}/ndk/27.0.12077973
ENV ANDROID_NDK_ROOT=${ANDROID_NDK_HOME}
ENV PATH="${ANDROID_NDK_HOME}:${PATH}"

# ── Drift CLI ─────────────────────────────────────────────────────────────────
ARG DRIFT_VERSION=v0.25.1
RUN go install github.com/go-drift/drift/cmd/drift@${DRIFT_VERSION}

# ── Pre-fetch Drift's Skia binaries for Android ───────────────────────────────
# This runs `drift fetch-skia android` in a temp project so the binaries are
# cached in ~/.drift before the actual build, avoiding a slow download at
# build time when the source is mounted.
RUN mkdir -p /tmp/skia-prefetch && \
    cd /tmp/skia-prefetch && \
    go mod init prefetch && \
    go get github.com/go-drift/drift@${DRIFT_VERSION} && \
    drift fetch-skia android 2>/dev/null || true && \
    rm -rf /tmp/skia-prefetch

# ── Source + build ────────────────────────────────────────────────────────────
WORKDIR /src/android

# Copy go.mod/go.sum first for better layer caching
COPY android/go.mod android/go.sum* ./
RUN go mod download

COPY android/ ./

# Default: build the APK and copy to /out/
RUN mkdir -p /out
CMD drift build android -o /out/newsapp.apk && \
    echo "Build complete: /out/newsapp.apk"
