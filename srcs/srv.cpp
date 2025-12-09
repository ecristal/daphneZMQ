#include <algorithm>
#include <array>
#include <cerrno>
#include <cctype>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <limits>
#include <memory>
#include <sstream>
#include <string>
#include <string_view>

#include <zmq.h>

#include "DevMem.hpp"

namespace {

constexpr uint64_t kAxiBaseAddr = 0x40000000ULL;  // Adjust to DAPHNE AXI base address
constexpr size_t kAxiWindowSize = 0x1000;         // Adjust to DAPHNE AXI memory size
constexpr std::string_view kDefaultBindEndpoint{"tcp://*:9000"};
constexpr size_t kMaxRequestSize = 256;

uint32_t parse_u32_token(const std::string& token) {
    if (token.empty()) {
        throw std::invalid_argument("missing value");
    }
    size_t consumed = 0;
    unsigned long raw = std::stoul(token, &consumed, 0);
    if (consumed != token.size()) {
        throw std::invalid_argument("trailing characters in value '" + token + "'");
    }
    if (raw > std::numeric_limits<uint32_t>::max()) {
        throw std::out_of_range("value '" + token + "' exceeds uint32_t range");
    }
    return static_cast<uint32_t>(raw);
}

std::string resolve_bind_endpoint(int argc, char** argv) {
    if (argc > 1 && argv[1] && std::strlen(argv[1]) != 0) {
        return argv[1];
    }
    if (const char* from_env = std::getenv("DAPHNEZMQ_BIND")) {
        if (std::strlen(from_env) != 0) {
            return from_env;
        }
    }
    return std::string{kDefaultBindEndpoint};
}

struct ZmqContextDeleter {
    void operator()(void* ctx) const noexcept {
        if (ctx) {
            zmq_ctx_term(ctx);
        }
    }
};

struct ZmqSocketDeleter {
    void operator()(void* socket) const noexcept {
        if (socket) {
            zmq_close(socket);
        }
    }
};

using ZmqContextPtr = std::unique_ptr<void, ZmqContextDeleter>;
using ZmqSocketPtr = std::unique_ptr<void, ZmqSocketDeleter>;

ZmqContextPtr create_zmq_context() {
    void* raw_ctx = zmq_ctx_new();
    if (!raw_ctx) {
        throw std::runtime_error("Failed to create ZeroMQ context: " +
                                 std::string(zmq_strerror(zmq_errno())));
    }
    return ZmqContextPtr{raw_ctx};
}

ZmqSocketPtr create_rep_socket(void* context, const std::string& endpoint) {
    void* raw_socket = zmq_socket(context, ZMQ_REP);
    if (!raw_socket) {
        throw std::runtime_error("Failed to create ZeroMQ socket: " +
                                 std::string(zmq_strerror(zmq_errno())));
    }

    // Avoid blocking on shutdown if the peer disappears.
    const int linger_ms = 0;
    (void)zmq_setsockopt(raw_socket, ZMQ_LINGER, &linger_ms, sizeof(linger_ms));

    if (zmq_bind(raw_socket, endpoint.c_str()) != 0) {
        zmq_close(raw_socket);
        throw std::runtime_error("Failed to bind ZeroMQ socket to " + endpoint +
                                 ": " + std::string(zmq_strerror(zmq_errno())));
    }

    return ZmqSocketPtr{raw_socket};
}

std::string handle_request(std::string_view request, DevMem& devmem) {
    if (request.empty()) {
        return "ERROR: expected <command> <offset> [value]";
    }

    std::istringstream line(std::string(request));
    std::string command;
    std::string offset_token;
    std::string value_token;

    if (!(line >> command >> offset_token)) {
        return "ERROR: expected <command> <offset> [value]";
    }

    std::transform(command.begin(),
                   command.end(),
                   command.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });

    const uint32_t offset = parse_u32_token(offset_token);

    if (command == "write") {
        if (!(line >> value_token)) {
            return "ERROR: missing value for write command";
        }
        const uint32_t value = parse_u32_token(value_token);
        devmem.write_u32(offset, value);
        const uint32_t read_back = devmem.read_u32(offset);
        if (read_back == value) {
            return "OK";
        }
        std::ostringstream os;
        os << "ERROR: verify failed (expected 0x"
           << std::hex << value << " read 0x" << read_back << ")";
        return os.str();
    }

    if (command == "read") {
        const uint32_t data = devmem.read_u32(offset);
        std::ostringstream os;
        os << std::hex << std::uppercase;
        os.width(8);
        os.fill('0');
        os << data;
        return os.str();
    }

    return "ERROR: unsupported command '" + command + "'";
}

}  // namespace

int main(int argc, char** argv) {
    try {
        DevMem devmem(kAxiBaseAddr);
        devmem.map_memory(kAxiWindowSize);

        const std::string bind_endpoint = resolve_bind_endpoint(argc, argv);

        auto context = create_zmq_context();
        auto socket = create_rep_socket(context.get(), bind_endpoint);

        std::cout << "srv bound to " << bind_endpoint << std::endl;

        std::array<char, kMaxRequestSize> buffer{};
        auto send_reply = [&socket](const std::string& msg) {
            if (zmq_send(socket.get(), msg.data(), msg.size(), 0) == -1) {
                std::cerr << "Failed to send reply: "
                          << zmq_strerror(zmq_errno()) << std::endl;
            }
        };

        while (true) {
            const int bytes_received =
                zmq_recv(socket.get(), buffer.data(), buffer.size() - 1, 0);
            if (bytes_received == -1) {
                const int err = zmq_errno();
                if (err == EINTR) {
                    continue;
                }
                throw std::runtime_error("ZeroMQ receive failed: " +
                                         std::string(zmq_strerror(err)));
            }

            buffer[bytes_received] = '\0';

            try {
                const std::string reply = handle_request(
                    std::string_view(buffer.data(), static_cast<size_t>(bytes_received)),
                    devmem);
                send_reply(reply);
            } catch (const std::exception& cmd_err) {
                send_reply(std::string("ERROR: ") + cmd_err.what());
            }
        }
    } catch (const std::exception& e) {
        std::cerr << "srv encountered a fatal error: " << e.what() << std::endl;
        return EXIT_FAILURE;
    }

    return EXIT_SUCCESS;
}
