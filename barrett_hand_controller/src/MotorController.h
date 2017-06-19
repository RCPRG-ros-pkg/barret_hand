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

#ifndef _MOTOR_CONTROLLER_H_
#define _MOTOR_CONTROLLER_H_

#include <inttypes.h>
#include <controller_common/can_queue_service_requester.h>

class MotorController {
public:
	typedef int32_t tact_array_t[24];
	MotorController(RTT::TaskContext *owner, const std::string &dev_name, int can_id_base);
	~MotorController();
/*
	void initHand();
	void stopHand();
	void stopFinger(int32_t id);
	void resetFinger(int id);
	void open(int id);
	void close(int id);
	void getPosition(int puck_id, int32_t &p, int32_t &jp);
	void getPositionAll(int32_t &p1, int32_t &p2, int32_t &p3, int32_t &jp1, int32_t &jp2, int32_t &jp3, int32_t &s);
	void setMaxVel(int id, uint32_t vel);
	void setMaxTorque(int id, uint32_t vel);
	void setCloseTarget(int id, uint32_t ct);
	void setOpenTarget(int id, uint32_t ot);
	void setTargetPos(int puck_id, int32_t pos);
	void setTargetVel(int puck_id, int32_t pos);
	void getCurrents(double &c1, double &c2, double &c3, double &c4);
	void setHoldPosition(int id, bool hold);
	void moveAll();
	void moveAllVel();
	void getStatus(int puck_id, int32_t &mode);
	void getStatusAll(int32_t &mode1, int32_t &mode2, int32_t &mode3, int32_t &mode4);
    void getTemp(int id, int32_t &temp);
    void getTherm(int id, int32_t &temp);
//	void getCts(int id, int32_t &cts);
*/
	void stopFinger(int32_t id);
    void resetFinger(int id);
    void setMaxVel(int id, uint32_t vel);
    void sendGetPosition(int puck_id);
    void getPosition(int puck_id, int32_t &p, int32_t &jp);
    void sendGetStatus(int puck_id);
    void getStatus(int puck_id, int32_t &mode);
    void sendGetCurrent(int puck_id);
    void getCurrent(int puck_id, double &c);
    void setHoldPosition(int id, bool hold);
	void setMaxTorque(int id, uint32_t vel);
	void setTargetPos(int puck_id, int32_t pos);
	void moveAll();
    void move(int puck_id);

	bool isDevOpened();
protected:
	void setProperty(int id, uint32_t property, int32_t value);
	void reqProperty(int id, uint32_t property);
	bool recEncoder2(int id, int32_t &p, int32_t &jp);
	bool recProperty(int id, int32_t &value);
//	int32_t getParameter(int32_t id, int32_t prop_id);
	void setParameter(int32_t id, int32_t prop_id, int32_t value, bool save);

    boost::shared_ptr<controller_common::CanQueueServiceRequester > can_srv_;
    int can_id_base_;
};

#endif

