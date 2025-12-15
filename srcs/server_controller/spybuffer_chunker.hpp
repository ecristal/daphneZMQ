#pragma once

#include <functional>

class Daphne;

namespace daphne {
class DumpSpyBuffersChunkRequest;
class DumpSpyBuffersChunkResponse;
}  // namespace daphne

namespace daphne_sc {

void for_each_spybuffer_chunk(
    const daphne::DumpSpyBuffersChunkRequest& request,
    Daphne& daphne,
    const std::function<void(const daphne::DumpSpyBuffersChunkResponse&)>& on_chunk);

}  // namespace daphne_sc

