#ifndef SPYBUFFER_FRESHNESS_HPP
#define SPYBUFFER_FRESHNESS_HPP

#include <optional>

template <typename TimestampKey>
TimestampKey selectExternalTriggerBaseline(
    const TimestampKey& current,
    const std::optional<TimestampKey>& last_delivered) {
    return last_delivered.value_or(current);
}

#endif
