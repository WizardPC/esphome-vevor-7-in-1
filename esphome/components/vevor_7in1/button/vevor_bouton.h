#pragma once
// Diagnostic buttons owned by the component (see button/__init__.py).
//
// No logic here: each button calls a public method of the component, so the "Re-apply radio
// config" button and the watchdog literally share the same re-arm.

#include "esphome/components/button/button.h"

#include "../vevor_7in1.h"

namespace esphome {
namespace vevor_7in1 {

class VevorBouton : public button::Button, public Parented<Vevor7in1> {
 public:
  void set_type(uint8_t t) { this->type_ = t; }

 protected:
  void press_action() override {
    if (this->type_ == 1) {
      this->parent_->reapply_radio();
    } else {
      this->parent_->request_raw_dump();
    }
  }

  uint8_t type_{0};
};

}  // namespace vevor_7in1
}  // namespace esphome
