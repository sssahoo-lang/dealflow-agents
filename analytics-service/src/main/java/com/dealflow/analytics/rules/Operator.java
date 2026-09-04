package com.dealflow.analytics.rules;

import java.util.Arrays;
import java.util.Optional;

/** Comparison operators available inside a rule condition. */
public enum Operator {
    EQ("eq"),
    NEQ("neq"),
    GT("gt"),
    GTE("gte"),
    LT("lt"),
    LTE("lte"),
    IN("in"),
    NOT_IN("not_in"),
    IS_NULL("is_null"),
    NOT_NULL("not_null");

    private final String wire;

    Operator(String wire) {
        this.wire = wire;
    }

    public String wire() {
        return wire;
    }

    public static Optional<Operator> fromWire(String wire) {
        return Arrays.stream(values()).filter(o -> o.wire.equals(wire)).findFirst();
    }
}
