#pragma once
// Watchdog setting, changeable from Home Assistant.
//
// No policy here: the value is handed to the component, which alone owns the policy
// (Vevor7in1::surveiller_radio_()). See dev/docs/firmware-design-notes.md §8.

#include "esphome/core/component.h"
#include "esphome/components/number/number.h"

#include "../vevor_7in1.h"

namespace esphome {
namespace vevor_7in1 {

// `number::Number` hérite seulement d'EntityBase, qui n'a PAS de setup() : pour publier l'état
// initial, il faut mélanger aussi Component — c'est ce que fait le composant `template` d'ESPHome
// (TemplateNumber : number::Number, PollingComponent). Erreur mesurée sinon, à la compilation :
// « setup() marked 'override', but does not override ».
class VevorParametre : public number::Number, public Component, public Parented<Vevor7in1> {
 public:
  void set_parametre(uint8_t p) { this->parametre_ = p; }
  void setup() override { this->publish_state(this->parent_->get_parametre(this->parametre_)); }

 protected:
  void control(float value) override {
    this->parent_->set_parametre(this->parametre_, value);
    this->publish_state(value);
  }

  uint8_t parametre_{0};
};

}  // namespace vevor_7in1
}  // namespace esphome
