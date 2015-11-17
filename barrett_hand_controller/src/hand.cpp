/*
 Copyright (c) 2014, Robot Control and Pattern Recognition Group, Warsaw University of Technology
 All rights reserved.
 
 Redistribution and use in source and binary forms, with or without
 modification, are permitted provided that the following conditions are met:
     * Redistributions of source code must retain the above copyright
       notice, this list of conditions and the following disclaimer.
     * Redistributions in binary form must reproduce the above copyright
       notice, this list of conditions and the following disclaimer in the
       documentation and/or other materials provided with the distribution.
     * Neither the name of the Warsaw University of Technology nor the
       names of its contributors may be used to endorse or promote products
       derived from this software without specific prior written permission.
 
 THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
 ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
 WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
 DISCLAIMED. IN NO EVENT SHALL <COPYright HOLDER> BE LIABLE FOR ANY
 DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
 (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
 LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
 ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
 SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
*/

#include <barrett_hand_controller_msgs/BHTemp.h>

#include <rtt/TaskContext.hpp>
#include <rtt/Port.hpp>
#include <rtt/RTT.hpp>
#include <rtt/Component.hpp>

#include <ros/ros.h>
#include <std_msgs/Empty.h>
#include <std_msgs/Int32.h>

#include "rtt_rosclock/rtt_rosclock.h"

#include <string>
#include <math.h>
#include "MotorController.h"

#include <fcntl.h>
#include <stdlib.h>
#include <sys/types.h>
#include <sys/stat.h>

#include "Eigen/Dense"

#define RAD2P(x) (static_cast<double>(x) * 180.0/3.1416 / 140.0 * 199111.1)
#define RAD2S(x) (static_cast<double>(x) * 35840.0/M_PI)

using std::string;
using RTT::InputPort;
using RTT::OutputPort;

class BarrettHand : public RTT::TaskContext {
private:
        const int BH_DOF;
    const int BH_JOINTS;
    const int TEMP_MAX_HI;
    const int TEMP_MAX_LO;
    enum {STATUS_OVERCURRENT1 = 0x0001, STATUS_OVERCURRENT2 = 0x0002, STATUS_OVERCURRENT3 = 0x0004, STATUS_OVERCURRENT4 = 0x0008,
        STATUS_OVERPRESSURE1 = 0x0010, STATUS_OVERPRESSURE2 = 0x0020, STATUS_OVERPRESSURE3 = 0x0040,
        STATUS_TORQUESWITCH1 = 0x0100, STATUS_TORQUESWITCH2 = 0x0200, STATUS_TORQUESWITCH3 = 0x0400,
        STATUS_IDLE1 = 0x1000, STATUS_IDLE2 = 0x2000, STATUS_IDLE3 = 0x4000, STATUS_IDLE4 = 0x8000 };

    int32_t loop_counter_;
    MotorController *ctrl_;

    int32_t maxStaticTorque_;
    int torqueSwitch_;

    bool hold_;
    bool holdEnabled_;

    // port variables
    Eigen::VectorXd q_in_;
    Eigen::VectorXd v_in_;
    Eigen::VectorXd t_in_;
    int32_t mp_in_;
    int32_t hold_in_;
    uint32_t status_out_;
    Eigen::Vector4d max_measured_pressure_in_;
    Eigen::VectorXd q_out_;
    Eigen::VectorXd t_out_;
    barrett_hand_controller_msgs::BHTemp temp_out_;

    std_msgs::Empty reset_in_;
    std_msgs::Empty calibrate_in_;
    std_msgs::Int32 filter_in_;

    // OROCOS ports
    InputPort<Eigen::VectorXd> port_q_in_;
    InputPort<Eigen::VectorXd> port_v_in_;
    InputPort<Eigen::VectorXd> port_t_in_;
    InputPort<int32_t> port_mp_in_;
    InputPort<int32_t> port_hold_in_;
    InputPort<Eigen::Vector4d > port_max_measured_pressure_in_;
    InputPort<std_msgs::Empty> port_reset_in_;
    OutputPort<uint32_t> port_status_out_;
    OutputPort<Eigen::VectorXd> port_q_out_;
    OutputPort<Eigen::VectorXd> port_t_out_;
    OutputPort<barrett_hand_controller_msgs::BHTemp> port_temp_out_;


    // ROS parameters
    string dev_name_;
    string prefix_;

    int resetFingersCounter_;

    int32_t p1, p2, p3, jp1, jp2, jp3, jp4, s;

public:
    explicit BarrettHand(const string& name):
        TaskContext(name, PreOperational),
        BH_DOF(4),
        BH_JOINTS(8),
        TEMP_MAX_HI(65),
        TEMP_MAX_LO(60),
        loop_counter_(0),
        resetFingersCounter_(0),
        maxStaticTorque_(4700),
        torqueSwitch_(-1),
        ctrl_(NULL),
        p1(0), p2(0), p3(0), jp1(0), jp2(0), jp3(0), jp4(0), s(0)
    {
        holdEnabled_ = false;
        hold_ = true;
        status_out_ = 0;
        mp_in_ = 0;

        this->ports()->addPort("q_in", port_q_in_);
        this->ports()->addPort("v_in", port_v_in_);
        this->ports()->addPort("t_in", port_t_in_);
        this->ports()->addPort("mp_in", port_mp_in_);
        this->ports()->addPort("hold_in", port_hold_in_);

        this->ports()->addPort("q_out", port_q_out_);
        this->ports()->addPort("t_out", port_t_out_);
        this->ports()->addPort("status_out", port_status_out_);

        this->ports()->addPort("BHTemp", port_temp_out_);

        this->ports()->addPort("max_measured_pressure_in", port_max_measured_pressure_in_);
        this->ports()->addPort("reset_fingers", port_reset_in_);

        this->addProperty("device_name", dev_name_);
        this->addProperty("prefix", prefix_);
    }

    ~BarrettHand() {
    }

    void cleanupHook() {
        if (ctrl_ != NULL) {
            delete ctrl_;
        }
    }

    // RTT configure hook
    bool configureHook() {
        if (ctrl_ == NULL && !dev_name_.empty() && !prefix_.empty()) {
            ctrl_ = new MotorController(dev_name_);

            q_in_.resize(BH_DOF);
            v_in_.resize(BH_DOF);
            t_in_.resize(BH_DOF);
            t_out_.resize(BH_JOINTS);
            q_out_.resize(BH_JOINTS);
            temp_out_.temp.resize(BH_JOINTS);

            port_q_out_.setDataSample(q_out_);
            port_t_out_.setDataSample(t_out_);

            port_temp_out_.setDataSample(temp_out_);

            max_measured_pressure_in_.setZero();

            if (ctrl_->isDevOpened()) {
                return true;
            }
            return false;
        }
        return false;
    }

    // RTT start hook
    bool startHook()
    {
        holdEnabled_ = false;
        hold_ = true;
        status_out_ = 0;
        ctrl_->setHoldPosition(0, false);
        ctrl_->setHoldPosition(1, false);
        ctrl_->setHoldPosition(2, false);
        ctrl_->setHoldPosition(3, false);

        ctrl_->setMaxVel(0, RAD2P(1)/1000.0);
        ctrl_->setMaxVel(1, RAD2P(1)/1000.0);
        ctrl_->setMaxVel(2, RAD2P(1)/1000.0);
        ctrl_->setMaxVel(3, RAD2S(0.7)/1000.0);

        return true;
    }

    void stopHook()
    {
        ctrl_->stopHand();
    }

    // RTT update hook
    // This function runs every 1 ms (1000 Hz).
    // Temperature is published every 100 ms (10 Hz).
    void updateHook()
    {
        if (port_reset_in_.read(reset_in_) == RTT::NewData) {
            resetFingersCounter_ = 3000;
        }

        if (resetFingersCounter_ > 0)
        {
            --resetFingersCounter_;
            if (resetFingersCounter_ == 2500)
            {
                ctrl_->resetFinger(0);
            }
            else if (resetFingersCounter_ == 2505)
            {
                ctrl_->resetFinger(1);
            }
            else if (resetFingersCounter_ == 2510)
            {
                ctrl_->resetFinger(2);
            }
            else if (resetFingersCounter_ == 2000) {
                ctrl_->resetFinger(3);
            }
            return;
        }

        bool move_hand = false;

        if (port_q_in_.read(q_in_) == RTT::NewData) {
            if (q_in_.size() == BH_DOF) {
                move_hand = true;
            } else {
                RTT::log(RTT::Warning) << "Size of " << port_q_in_.getName()
                << " not equal to " << BH_DOF << RTT::endlog();
            }
        }

        if (port_v_in_.read(v_in_) == RTT::NewData) {
            if (v_in_.size() == BH_DOF) {
                ctrl_->setMaxVel(0, RAD2P(v_in_[0])/1000.0);
                ctrl_->setMaxVel(1, RAD2P(v_in_[1])/1000.0);
                ctrl_->setMaxVel(2, RAD2P(v_in_[2])/1000.0);
                ctrl_->setMaxVel(3, RAD2S(v_in_[3])/1000.0);
            } else {
                RTT::log(RTT::Warning) << "Size of " << port_v_in_.getName()
                << " not equal to " << BH_DOF << RTT::endlog();
            }
        }

        if (port_t_in_.read(t_in_) == RTT::NewData) {
            if (t_in_.size() == BH_DOF) {
            } else {
                RTT::log(RTT::Warning) << "Size of " << port_t_in_.getName()
                << " not equal to " << BH_DOF << RTT::endlog();
            }
        }

        port_mp_in_.read(mp_in_);
        if (port_hold_in_.read(hold_in_) == RTT::NewData) {
            holdEnabled_ = static_cast<bool>(hold_in_);
            ctrl_->setHoldPosition(3, holdEnabled_ && hold_);
        }

        if (move_hand) {
            status_out_ = 0;        // clear the status

            for (int i=0; i<BH_DOF; i++) {
                ctrl_->setMaxTorque(i, maxStaticTorque_);
            }
            torqueSwitch_ = 5;

            ctrl_->setTargetPos(0, RAD2P(q_in_[0]));
            ctrl_->setTargetPos(1, RAD2P(q_in_[1]));
            ctrl_->setTargetPos(2, RAD2P(q_in_[2]));
            ctrl_->setTargetPos(3, RAD2S(q_in_[3]));
            ctrl_->moveAll();
        }

        if (torqueSwitch_>0)
        {
            --torqueSwitch_;
        } else if (torqueSwitch_ == 0)
        {
            for (int i=0; i<BH_DOF; i++) {
                ctrl_->setMaxTorque(i, t_in_[i]);
            }
            --torqueSwitch_;
        }

        // write current joint positions
        ctrl_->getPositionAll(p1, p2, p3, jp1, jp2, jp3, s);
        q_out_[0] = static_cast<double>(s) * M_PI/ 35840.0;
        q_out_[1] = 2.0*M_PI/4096.0*static_cast<double>(jp1)/50.0;
        q_out_[2] = 2.0*M_PI/4096.0*static_cast<double>(p1)*(1.0/125.0 + 1.0/375.0) - q_out_[1];
        q_out_[3] = static_cast<double>(s) * M_PI/ 35840.0;
        q_out_[4] = 2.0*M_PI*static_cast<double>(jp2)/4096.0/50.0;
        q_out_[5] = 2.0*M_PI/4096.0*(double)(p2)*(1.0/125.0 + 1.0/375.0) - q_out_[4];
        q_out_[6] = 2.0*M_PI*static_cast<double>(jp3)/4096.0/50.0;
        q_out_[7] = 2.0*M_PI/4096.0*static_cast<double>(p3)*(1.0/125.0 + 1.0/375.0) - q_out_[6];
        port_q_out_.write(q_out_);

        // on 1, 101, 201, 301, 401, ... step
        if ( (loop_counter_%100) == 1)
        {
            int32_t temp[4] = {0,0,0,0}, therm[4] = {0,0,0,0};
            bool allTempOk = true;
            bool oneTempTooHigh = false;

            temp_out_.header.stamp = rtt_rosclock::host_now();

            for (int i=0; i<4; i++) {
                ctrl_->getTemp(i, temp[i]);
                ctrl_->getTherm(i, therm[i]);

                if (temp[i] > TEMP_MAX_HI || therm[i] > TEMP_MAX_HI) {
                    oneTempTooHigh = true;
                } else if (temp[i] >= TEMP_MAX_LO || therm[i] >= TEMP_MAX_LO) {
                    allTempOk = false;
                }
                temp_out_.temp[i] = temp[i];
                temp_out_.temp[4+i] = therm[i];
            }

            if (hold_ && oneTempTooHigh) {
                hold_ = false;
                ctrl_->setHoldPosition(3, holdEnabled_ && hold_);
                RTT::log(RTT::Warning) << "Temperature is too high. Disabled spread hold." << RTT::endlog();
            } else if (!hold_ && allTempOk) {
                hold_ = true;
                ctrl_->setHoldPosition(3, holdEnabled_ && hold_);
                RTT::log(RTT::Warning) << "Temperature is lower. Enabled spread hold." << RTT::endlog();
            }

            port_temp_out_.write(temp_out_);
        }

        port_max_measured_pressure_in_.read(max_measured_pressure_in_);

//        std::cout << max_measured_pressure_in_.transpose() << "   " << mp_in_ << std::endl;
//        if (resetFingersCounter_ <= 0) {
//        }

        int32_t mode[4] = {0, 0, 0, 0};
        ctrl_->getStatusAll(mode[0], mode[1], mode[2], mode[3]);

        // chack for torque switch activation
        if (fabs(q_out_[2]*3.0-q_out_[1]) > 0.03) {
            status_out_ |= STATUS_TORQUESWITCH1;
        }
        if (fabs(q_out_[5]*3.0-q_out_[4]) > 0.03) {
            status_out_ |= STATUS_TORQUESWITCH2;
        }
        if (fabs(q_out_[7]*3.0-q_out_[6]) > 0.03) {
            status_out_ |= STATUS_TORQUESWITCH3;
        }

        if (mode[0] == 0) {
            status_out_ |= STATUS_IDLE1;
            if ((status_out_&STATUS_OVERPRESSURE1) == 0 && fabs(q_in_[0]-q_out_[1]) > 0.03) {
                status_out_ |= STATUS_OVERCURRENT1;
            }
        }

        if (mode[1] == 0) {
            status_out_ |= STATUS_IDLE2;
            if ((status_out_&STATUS_OVERPRESSURE2) == 0 && fabs(q_in_[1]-q_out_[4]) > 0.03) {
                status_out_ |= STATUS_OVERCURRENT2;
            }
        }

        if (mode[2] == 0) {
            status_out_ |= STATUS_IDLE3;
            if ((status_out_&STATUS_OVERPRESSURE3) == 0 && fabs(q_in_[2]-q_out_[6]) > 0.03) {
                status_out_ |= STATUS_OVERCURRENT3;
            }
        }

        if (mode[3] == 0 || (holdEnabled_ && fabs(q_in_[3]-q_out_[3]) < 0.05)) {
            status_out_ |= STATUS_IDLE4;
            if (fabs(q_in_[3]-q_out_[3]) > 0.03) {
                status_out_ |= STATUS_OVERCURRENT4;
            }
        }

        bool f1_stopped(false), f2_stopped(false), f3_stopped(false);
        for (int j=0; j<24; ++j) {
            if ( (status_out_&STATUS_IDLE1) == 0 && !f1_stopped) {
                if (max_measured_pressure_in_(0) > mp_in_) {
                    ctrl_->stopFinger(0);
                    status_out_ |= STATUS_OVERPRESSURE1;
                    f1_stopped = true;
                }
            }
            if ( (status_out_&STATUS_IDLE2) == 0 && !f2_stopped) {
                if (max_measured_pressure_in_(1) > mp_in_) {
                    ctrl_->stopFinger(1);
                    status_out_ |= STATUS_OVERPRESSURE2;
                    f2_stopped = true;
                }
            }
            if ( (status_out_&STATUS_IDLE3) == 0 && !f3_stopped) {
                if (max_measured_pressure_in_(2) > mp_in_) {
                    ctrl_->stopFinger(2);
                    status_out_ |= STATUS_OVERPRESSURE3;
                    f3_stopped = true;
                }
            }
        }

        double currents[4] = {0.0, 0.0, 0.0, 0.0};
        ctrl_->getCurrents(currents[0], currents[1], currents[2], currents[3]);
        t_out_[0] = currents[3];
        t_out_[1] = currents[0];
        t_out_[2] = currents[0];
        t_out_[3] = currents[3];
        t_out_[4] = currents[1];
        t_out_[5] = currents[1];
        t_out_[6] = currents[2];
        t_out_[7] = currents[2];

        port_t_out_.write(t_out_);

        port_status_out_.write(status_out_);

        loop_counter_ = (loop_counter_+1)%1000;
    }
};
ORO_CREATE_COMPONENT(BarrettHand)

