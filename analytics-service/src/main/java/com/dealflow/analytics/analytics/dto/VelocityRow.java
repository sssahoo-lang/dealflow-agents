package com.dealflow.analytics.dto;

/**
 * How long deals sit in a stage before moving on.
 *
 * @param sampleSize transitions observed; a small sample makes the average noise,
 *                   so it is returned rather than hidden behind the number
 */
public record VelocityRow(String stage, Double avgDays, Double medianDays, long sampleSize) {}
