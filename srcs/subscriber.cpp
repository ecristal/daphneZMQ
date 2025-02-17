#include <iostream>
#include <zmq.hpp>

int main() {
    // Create a context for the subscriber
    zmq::context_t context(1);

    // Create a subscriber socket
    zmq::socket_t subscriber(context, zmq::socket_type::sub);
    subscriber.connect("tcp://193.206.157.36:9000");

    // Subscribe to all messages
    subscriber.set(zmq::sockopt::subscribe, "");

    std::cout << "Subscriber connected to tcp://193.206.157.36:9000" << std::endl;

    while (true) {
        zmq::message_t message;
        subscriber.recv(message, zmq::recv_flags::none);
        std::cout << "Received message: " << message.to_string() << std::endl;
    }

    return 0;
}
