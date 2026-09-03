# Multi-stage: Maven builds inside the image, so no JDK or Maven is needed on the
# host. `docker compose up` is the only entry point.

FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /build

# Resolve dependencies against the pom alone first, so editing a source file
# doesn't re-download the world on every rebuild.
COPY pom.xml .
RUN mvn -B -q dependency:go-offline

COPY src/ src/
# Tests are skipped here deliberately: `docker build` has no Docker daemon, so
# anything Testcontainers-based cannot run at image-build time. The suite runs
# via the `analytics-test` compose profile instead, against the real db service.
RUN mvn -B -q clean package -DskipTests

FROM eclipse-temurin:21-jre-jammy AS runtime
WORKDIR /app

# curl is only here for the compose healthcheck; the JRE image doesn't ship it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Don't run as root.
RUN useradd --system --uid 10001 --create-home analytics
USER analytics

COPY --from=build /build/target/analytics-service-*.jar app.jar

EXPOSE 8081

# UTC everywhere: the DB, the API and this service all agree, so a rule about
# elapsed days can never be skewed by a container's local zone.
ENV JAVA_TOOL_OPTIONS="-Duser.timezone=UTC -XX:MaxRAMPercentage=75"

ENTRYPOINT ["java", "-jar", "app.jar"]
