package com.dealflow.analytics.security;

/**
 * The authenticated caller, resolved purely from JWT claims.
 *
 * <p>This service has no users table, so it cannot look an email up to find an id
 * or a role -- {@code uid} and {@code role} are carried in the token for exactly
 * this reason. Every query scopes on {@link #userId()} unless {@link #isAdmin()}.
 */
public record Principal(long userId, String email, String role) {

    public static final String ATTRIBUTE = "analytics.principal";

    public boolean isAdmin() {
        return "admin".equals(role);
    }
}
