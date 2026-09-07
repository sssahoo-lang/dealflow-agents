package com.dealflow.analytics.security;

import java.time.Duration;

/**
 * Where to find the CRM's public signing keys, and how often to look.
 *
 * <p>Note what is <em>absent</em>: any signing material. This service verifies
 * tokens and can no longer mint them, which is the same boundary its SELECT-only
 * database role draws, expressed in the auth layer instead of in Postgres.
 *
 * @param jwksUri the CRM's RFC 8615 discovery document
 * @param refreshCooldown the minimum wait between refetches. An unrecognised
 *     {@code kid} triggers a refetch, and an unrecognised kid is attacker-
 *     controlled -- without a floor, a stream of junk tokens becomes a request
 *     amplifier pointed at the CRM.
 * @param timeout how long a single fetch may take before the token is rejected
 */
@org.springframework.boot.context.properties.ConfigurationProperties(prefix = "analytics.jwt")
public record JwtProperties(String jwksUri, Duration refreshCooldown, Duration timeout) {}
