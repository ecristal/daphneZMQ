#include <algorithm>
#include <array>
#include <cerrno>
#include <cctype>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <limits>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

#include <zmq.h>

#include "DevMem.hpp"

namespace {

constexpr uint64_t kAxiBaseAddr = 0x40000000ULL;  // Adjust to DAPHNE AXI base address
constexpr size_t kAxiWindowSize = 0x1000;         // Adjust to DAPHNE AXI memory size
constexpr std::string_view kDefaultBindEndpoint{"tcp://*:9000"};

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

}  // namespace

int main(int argc, char** argv) {
    void* context = nullptr;
    void* socket = nullptr;

    try {
        DevMem devmem(kAxiBaseAddr);
        devmem.map_memory(kAxiWindowSize);

        const std::string bind_endpoint = resolve_bind_endpoint(argc, argv);

        context = zmq_ctx_new();
        if (!context) {
            throw std::runtime_error("Failed to create ZeroMQ context: " +
                                     std::string(zmq_strerror(zmq_errno())));
        }

        socket = zmq_socket(context, ZMQ_REP);
        if (!socket) {
            throw std::runtime_error("Failed to create ZeroMQ socket: " +
                                     std::string(zmq_strerror(zmq_errno())));
        }

        if (zmq_bind(socket, bind_endpoint.c_str()) != 0) {
            throw std::runtime_error("Failed to bind ZeroMQ socket to " + bind_endpoint +
                                     ": " + std::string(zmq_strerror(zmq_errno())));
        }

        std::cout << "srv bound to " << bind_endpoint << std::endl;

        std::array<char, 256> buffer{};
        auto send_reply = [socket](const std::string& msg) {
            if (zmq_send(socket, msg.data(), msg.size(), 0) == -1) {
                std::cerr << "Failed to send reply: "
                          << zmq_strerror(zmq_errno()) << std::endl;
            }
        };

        while (true) {
            const int bytes_received =
                zmq_recv(socket, buffer.data(), buffer.size() - 1, 0);
            if (bytes_received == -1) {
                const int err = zmq_errno();
                if (err == EINTR) {
                    continue;
                }
                throw std::runtime_error("ZeroMQ receive failed: " +
                                         std::string(zmq_strerror(err)));
            }

            buffer[bytes_received] = '\0';

            std::istringstream line(buffer.data());
            std::string command;
            std::string offset_token;
            std::string value_token;

            if (!(line >> command >> offset_token)) {
                send_reply("ERROR: expected <command> <offset> [value]");
                continue;
            }

            std::transform(command.begin(),
                           command.end(),
                           command.begin(),
                           [](unsigned char c) { return static_cast<char>(std::tolower(c)); });

            try {
                const uint32_t offset = parse_u32_token(offset_token);

                if (command == "write") {
                    if (!(line >> value_token)) {
                        send_reply("ERROR: missing value for write command");
                        continue;
                    }
                    const uint32_t value = parse_u32_token(value_token);
                    std::vector<uint32_t> data_vector(1, value);
                    devmem.write(offset, data_vector);
                    const auto confirm = devmem.read(offset, 1);
                    const uint32_t read_back = confirm.at(0);
                    if (read_back == value) {
                        send_reply("OK");
                    } else {
                        std::ostringstream os;
                        os << "ERROR: verify failed (expected 0x"
                           << std::hex << value << " read 0x" << read_back << ")";
                        send_reply(os.str());
                    }
                } else if (command == "read") {
                    const auto data = devmem.read(offset, 1);
                    std::ostringstream os;
                    os << std::hex << std::uppercase;
                    os.width(8);
                    os.fill('0');
                    os << data.at(0);
                    send_reply(os.str());
                } else {
                    send_reply("ERROR: unsupported command '" + command + "'");
                }
            } catch (const std::exception& cmd_err) {
                send_reply(std::string("ERROR: ") + cmd_err.what());
            }
        }
    } catch (const std::exception& e) {
        std::cerr << "srv encountered a fatal error: " << e.what() << std::endl;
        if (socket) {
            zmq_close(socket);
        }
        if (context) {
            zmq_ctx_term(context);
        }
        return EXIT_FAILURE;
    }

    zmq_close(socket);
    zmq_ctx_term(context);

    return EXIT_SUCCESS;
}
