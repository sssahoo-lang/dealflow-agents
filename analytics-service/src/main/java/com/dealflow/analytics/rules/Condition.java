package com.dealflow.analytics.rules;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.List;

/**
 * A rule condition, parsed from the JSONB stored in {@code rule_definition}.
 *
 * <p>Rules are data rather than code so they can be enabled, disabled and retuned
 * through the API without a redeploy, and so the evaluator stays a pure function
 * that is trivial to test at its boundaries.
 *
 * <p>Sealed: the evaluator's switch is exhaustive, so adding a node type without
 * handling it is a compile error rather than a silently unevaluated rule.
 */
public sealed interface Condition
        permits Condition.All, Condition.Any, Condition.Not, Condition.Comparison {

    /** Empty {@code all} is TRUE -- the vacuous truth of "every condition holds". */
    record All(List<Condition> conditions) implements Condition {}

    /** Empty {@code any} is FALSE -- no condition held, because there were none. */
    record Any(List<Condition> conditions) implements Condition {}

    record Not(Condition condition) implements Condition {}

    record Comparison(String field, Operator operator, JsonNode value) implements Condition {}
}
