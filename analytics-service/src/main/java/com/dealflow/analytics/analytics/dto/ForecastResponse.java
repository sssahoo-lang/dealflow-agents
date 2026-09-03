package com.dealflow.analytics.dto;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;

/**
 * @param weightedTotal sum of value x stage probability across open deals
 * @param rawPipeline   unweighted sum, for contrast
 * @param unscheduled   open deals with no expected close date; they are excluded
 *                      from the buckets, so surfacing the count stops the
 *                      forecast from silently under-reporting the pipeline
 */
public record ForecastResponse(
        int horizonMonths,
        Instant generatedAt,
        BigDecimal weightedTotal,
        BigDecimal rawPipeline,
        long unscheduledDealCount,
        BigDecimal unscheduledValue,
        List<ForecastBucket> buckets) {

    public record ForecastBucket(
            String month, BigDecimal weighted, BigDecimal raw, long dealCount) {}
}
