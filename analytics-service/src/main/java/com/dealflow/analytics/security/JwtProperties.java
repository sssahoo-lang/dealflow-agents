package com.dealflow.analytics.security;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * @param secret shared HS256 secret, the same one the Python API signs with.
 */
@ConfigurationProperties(prefix = "analytics.jwt")
public record JwtProperties(String secret) {}
