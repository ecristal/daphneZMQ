#include <iostream>
#include <zmq.hpp>
#include <thread>
#include <chrono>

int main() {
    // Create a context for the publisher
    zmq::context_t context(1);

    // Create a publisher socket
    zmq::socket_t publisher(context, zmq::socket_type::pub);
    publisher.bind("tcp://193.206.157.36:9000");

    std::cout << "Publisher bound to tcp://193.206.157.36:9000" << std::endl;

    // Send a message
    while (true) {
        zmq::message_t message("Hola desde DAPHNE Bicocca!");
        publisher.send(message, zmq::send_flags::none);
        std::cout << "Sent message: Hola desde DAPHNE Bicocca!" << std::endl;

        // Sleep for a while to avoid flooding
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }

    return 0;
}
