#pragma once
// Watchdog setting, changeable from Home Assistant.
//
// No policy here: the value is handed to the component, which alone owns the policy
// (Vevor7in1::watch_radio_()). See dev/docs/firmware-design-notes.md §8.

#include "esphome/core/component.h"
#include "esphome/components/number/number.h"

#include "../vevor_7in1.h"

namespace esphome {
namespace vevor_7in1 {

// `number::Number` inherits only from EntityBase, which has NO setup(): to publish the initial
// state it must also mix in Component — which is what ESPHome's `template` component does
// (TemplateNumber: number::Number, PollingComponent). Measured error otherwise, at compile time:
// « setup() marked 'override', but does not override ».
class VevorParameter : public number::Number, public Component, public Parented<Vevor7in1> {
 public:
  void set_parameter(uint8_t p) { this->parameter_ = p; }
  void setup() override { this->publish_state(this->parent_->get_parameter(this->parameter_)); }

 protected:
  void control(float value) override {
    this->parent_->set_parameter(this->parameter_, value);
    this->publish_state(value);
  }

  uint8_t parameter_{0};
};

}  // namespace vevor_7in1
}  // namespace esphome
