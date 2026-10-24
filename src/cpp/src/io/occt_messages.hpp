// Capture OpenCASCADE's diagnostic output (internal).
//
// The STEP translators narrate every transfer on the default messenger, which
// prints to stdout: noise for a library, but exactly the explanation a failed
// import needs.  A MessageCapture swaps the messenger's printers for a buffer for
// its lifetime, and gives the text back for an error message.  Take it while
// holding detail::data_exchange_mutex(): the messenger is process-global.
#pragma once

#include <string>
#include <vector>

#include <Message.hxx>
#include <Message_Messenger.hxx>
#include <Message_Printer.hxx>
#include <TCollection_AsciiString.hxx>

namespace scad::io::detail {

class MessageCapture {
 public:
  MessageCapture() : messenger_(Message::DefaultMessenger()), printer_(new Printer) {
    for (const Handle(Message_Printer)& existing : messenger_->Printers()) saved_.push_back(existing);
    messenger_->ChangePrinters().Clear();
    messenger_->AddPrinter(printer_);
  }
  ~MessageCapture() {
    messenger_->ChangePrinters().Clear();
    for (const Handle(Message_Printer)& existing : saved_) messenger_->AddPrinter(existing);
  }
  MessageCapture(const MessageCapture&) = delete;
  MessageCapture& operator=(const MessageCapture&) = delete;

  // The captured lines, trimmed and capped (the head is the most informative part).
  std::string text(std::size_t max_chars = 1500) const {
    std::string out = printer_->buffer;
    while (!out.empty() && (out.back() == '\n' || out.back() == ' ')) out.pop_back();
    if (out.size() > max_chars) out = out.substr(0, max_chars) + "...";
    return out;
  }

 private:
  class Printer : public Message_Printer {
   public:
    mutable std::string buffer;

   protected:
    void send(const TCollection_AsciiString& message, const Message_Gravity) const override {
      buffer += message.ToCString();
      buffer += '\n';
    }
  };

  Handle(Message_Messenger) messenger_;
  Handle(Printer) printer_;
  std::vector<Handle(Message_Printer)> saved_;
};

}  // namespace scad::io::detail
