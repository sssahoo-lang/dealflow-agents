package com.dealflow.analytics.rules;

/**
 * A rule referenced a fact that does not exist.
 *
 * <p>Thrown rather than treated as null so the engine can fail closed: a rule it
 * cannot evaluate must not fire. Failing open on a rules engine turns a typo into
 * a flood of false findings.
 */
public class UnknownFieldException extends RuntimeException {
    public UnknownFieldException(String field) {
        super("Unknown fact '" + field + "'");
    }
}
