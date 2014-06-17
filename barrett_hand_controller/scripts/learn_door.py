#!/usr/bin/env python

# Software License Agreement (BSD License)
#
# Copyright (c) 2011, Robot Control and Pattern Recognition Group, Warsaw University of Technology
#
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# * Redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
# * Neither the name of the <organization> nor the
# names of its contributors may be used to endorse or promote products
# derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYright HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL <COPYright HOLDER> BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import roslib
roslib.load_manifest('barrett_hand_controller')

import rospy
import tf

import ar_track_alvar.msg
from ar_track_alvar.msg import *
from std_msgs.msg import *
from geometry_msgs.msg import *
from barrett_hand_controller_srvs.msg import *
from barrett_hand_controller_srvs.srv import *
from cartesian_trajectory_msgs.msg import *
from visualization_msgs.msg import *
import actionlib
from actionlib_msgs.msg import *

import tf
from tf import *
from tf.transformations import * 
import tf_conversions.posemath as pm
from tf2_msgs.msg import *
import scipy.io as sio

import PyKDL
import math
from numpy import *
from scipy import optimize

# reference frames:
# B - robot's base
# R - camera
# W - wrist
# E - gripper
# F - finger distal link
# T - tool
# C - current contact point
# N - the end point of finger's nail

class DoorOpener:
    """
Class for opening door with velma robot.
"""
    def PoseToTuple(self, p):
        return [p.position.x, p.position.y, p.position.z], [p.orientation.x, p.orientation.y, p.orientation.z, p.orientation.w]

    def get_pressure_sensors_info_client(self):
        service_name = '/' + self.prefix + '_hand/get_pressure_info'
        rospy.wait_for_service(service_name)
        try:
            get_pressure_sensors_info = rospy.ServiceProxy(service_name, BHGetPressureInfo)
            resp = get_pressure_sensors_info()
            return resp.info
        except rospy.ServiceException, e:
            print "Service call failed: %s"%e

    def alvarMarkerCallback(self, data):
        marker_count = len(data.markers)

        for i in range(0, marker_count):
            if data.markers[i].id == self.door_makrer_id:
                self.door_marker_pose = self.PoseToTuple(data.markers[i].pose.pose)
                self.door_marker_visible = True

    def tactileCallback(self, data):
        self.max_tactile_value = 0.0
        fingers = [data.finger1_tip, data.finger2_tip, data.finger3_tip]
        for f in range(0,3):
            for i in range(0, 24):
                if fingers[f][i] > self.max_tactile_value:
                    self.max_tactile_value = fingers[f][i]
                    self.max_tactile_index = i
                    self.max_tactile_finger = f
        if self.tactile_force_min > self.max_tactile_value:
            self.tactile_force_min = self.max_tactile_value

    def sendNextEvent(self):
        pc = PointStamped()
        pc.header.frame_id = 'torso_base'
        pc.header.stamp = rospy.Time.now()
        pc.point = Point(self.pub_msg_id, 0, 0)
        self.pub_msg.publish(pc)
        self.pub_msg_id += 1

    def getMaxWrench(self):
        wrench = Wrench()
        for i in range(0,self.wrench_tab_len):
            if abs(self.wrench_tab[i].force.x) > wrench.force.x:
                wrench.force.x = abs(self.wrench_tab[i].force.x)
            if abs(self.wrench_tab[i].force.y) > wrench.force.y:
                wrench.force.y = abs(self.wrench_tab[i].force.y)
            if abs(self.wrench_tab[i].force.z) > wrench.force.z:
                wrench.force.z = abs(self.wrench_tab[i].force.z)
            if abs(self.wrench_tab[i].torque.x) > wrench.torque.x:
                wrench.torque.x = abs(self.wrench_tab[i].torque.x)
            if abs(self.wrench_tab[i].torque.y) > wrench.torque.y:
                wrench.torque.y = abs(self.wrench_tab[i].torque.y)
            if abs(self.wrench_tab[i].torque.z) > wrench.torque.z:
                wrench.torque.z = abs(self.wrench_tab[i].torque.z)
        return wrench

    def wrenchCallback(self, wrench):
        self.wrench_tab[self.wrench_tab_index] = wrench
        self.wrench_tab_index += 1
        if self.wrench_tab_index >= self.wrench_tab_len:
            self.wrench_tab_index = 0
        wfx = abs(wrench.force.x)
        wfy = abs(wrench.force.y)
        wfz = abs(wrench.force.z)
        wtx = abs(wrench.torque.x)
        wty = abs(wrench.torque.y)
        wtz = abs(wrench.torque.z)
        self.wrench_mean.force.x = self.wrench_mean.force.x * self.wrench_mean_count + wfx
        self.wrench_mean.force.y = self.wrench_mean.force.y * self.wrench_mean_count + wfy
        self.wrench_mean.force.z = self.wrench_mean.force.z * self.wrench_mean_count + wfz
        self.wrench_mean.torque.x = self.wrench_mean.torque.x * self.wrench_mean_count + wtx
        self.wrench_mean.torque.y = self.wrench_mean.torque.y * self.wrench_mean_count + wty
        self.wrench_mean.torque.z = self.wrench_mean.torque.z * self.wrench_mean_count + wtz
        self.wrench_mean_count += 1
        self.wrench_mean.force.x /= self.wrench_mean_count
        self.wrench_mean.force.y /= self.wrench_mean_count
        self.wrench_mean.force.z /= self.wrench_mean_count
        self.wrench_mean.torque.x /= self.wrench_mean_count
        self.wrench_mean.torque.y /= self.wrench_mean_count
        self.wrench_mean.torque.z /= self.wrench_mean_count
        if self.wrench_max.force.x < wfx:
            self.wrench_max.force.x = wfx
        if self.wrench_max.force.y < wfy:
            self.wrench_max.force.y = wfy
        if self.wrench_max.force.z < wfz:
            self.wrench_max.force.z = wfz
        if self.wrench_max.torque.x < wtx:
            self.wrench_max.torque.x = wtx
        if self.wrench_max.torque.y < wty:
            self.wrench_max.torque.y = wty
        if self.wrench_max.torque.z < wtz:
            self.wrench_max.torque.z = wtz
        if (wfx>self.current_max_wrench.force.x*2.0) or (wfy>self.current_max_wrench.force.y*2.0) or (wfz>self.current_max_wrench.force.z*2.0) or (wtx>self.current_max_wrench.torque.x*2.0) or (wty>self.current_max_wrench.torque.y*2.0) or (wtz>self.current_max_wrench.torque.z*2.0):
            self.wrench_emergency_stop = True

    def resetMarkCounters(self):
        self.wrench_max = Wrench()
        self.wrench_mean_count = 0
        self.wrench_mean = Wrench()
        self.tactile_force_min = 1000000.0

    def __init__(self):
        # parameters for learning

        # good parameters
        #self.learning_k_handle_x = 500.0
        #self.learning_k_open_x = 150.0
        #self.learning_k_open_y = 35.0
        #self.learning_r_a = 0.25

#        r = force/stiffness
        forces = [4.0, 8.0, 12.0]
        k_x = [30.0, 200.0, 500.0]
        k_y = [20.0, 100.0, 250.0]

        forces = [6.0, 10.0]
        k_x = [200.0, 500.0]
        k_y = [20.0, 100.0, 250.0]

        forces = [4.0, 6.0, 8.0, 10.0]
        k_x = [350.0]
        k_y = [20.0, 100.0]

        forces = [12.0]

        forces = [4.0, 6.0, 8.0, 10.0, 12.0]
        k_x = [200.0, 350.0, 500.0]
        k_y = [20.0, 60.0, 100.0]

        self.max_index = 45
        self.index = 44

        i = 0
        for forces_v in forces:
            for k_x_v in k_x:
                for k_y_v in k_y:
                    if i == self.index:
                        self.force = forces_v
                        self.learning_k_handle_x = k_x_v
                        self.learning_k_open_x = k_x_v
                        self.learning_k_open_y = k_y_v
                        self.learning_r_a = self.force / self.learning_k_open_y
                    i += 1

        self.r_a = self.learning_r_a
        self.k_handle = Wrench(Vector3(self.learning_k_handle_x, 35.0, 1000.0), Vector3(300.0, 300.0, 300.0))
        self.k_open = Wrench(Vector3(self.learning_k_open_x, self.learning_k_open_y, 1000.0), Vector3(300.0, 300.0, 300.0))

        print "parameters:"
        print "index: %s"%(self.index)
        print "force: %s"%(self.force)
        print "r_a: %s"%(self.learning_r_a)
        print "k_handle_x: %s"%(self.learning_k_handle_x)
        print "k_open_y: %s"%(self.learning_k_open_y)
#        exit(0)

        # parameters
        self.prefix="right"
        self.q_start = (0.0/180.0*numpy.pi, 0.0/180.0*numpy.pi, 0.0/180.0*numpy.pi, 180.0/180.0*numpy.pi) 
#        self.q_door = (40.0/180.0*numpy.pi, 40.0/180.0*numpy.pi, 40.0/180.0*numpy.pi, 180.0/180.0*numpy.pi)
        self.q_door = (120.0/180.0*numpy.pi, 120.0/180.0*numpy.pi, 40.0/180.0*numpy.pi, 180.0/180.0*numpy.pi)
        self.q_handle = (75.0/180.0*numpy.pi, 75.0/180.0*numpy.pi, 75.0/180.0*numpy.pi, 180.0/180.0*numpy.pi)
        self.q_close = (120.0/180.0*numpy.pi, 120.0/180.0*numpy.pi, 120.0/180.0*numpy.pi, 180.0/180.0*numpy.pi)
#        self.P_s = PyKDL.Vector(0.0, -0.12, 0.3)
        self.P_s = []
        self.P_s.append( PyKDL.Vector(0.05, -0.12, 0.25) )
        self.P_s.append( PyKDL.Vector(-0.05, 0.0, 0.25) )
        self.P_s.append( PyKDL.Vector(0.05, 0, 0.25) )
        self.P_e1 = PyKDL.Vector(0.30, -0.30, 0.2)
        self.P_e2 = PyKDL.Vector(0.0, -0.30, 0.15)
        self.P_e3 = PyKDL.Vector(0.0, -0.25, 0.25)
        self.r_a = self.learning_r_a
        self.d_init = 0.1
        self.alpha_open = 110.0/180.0*numpy.pi
        self.delta = 0.02
        self.delta_e = 0.05
        self.k_door = Wrench(Vector3(200.0, 800.0, 800.0), Vector3(200.0, 200.0, 200.0))
        self.k_door2 = Wrench(Vector3(800.0, 800.0, 800.0), Vector3(200.0, 200.0, 200.0))
        self.k_handle = Wrench(Vector3(self.learning_k_handle_x, 35.0, 1000.0), Vector3(300.0, 300.0, 300.0))
        self.k_open = Wrench(Vector3(self.learning_k_open_x, self.learning_k_open_y, 1000.0), Vector3(300.0, 300.0, 300.0))
        self.k_error = Wrench(Vector3(10.0, 10.0, 10.0), Vector3(2.0, 2.0, 2.0))
        self.k_close = Wrench(Vector3(400.0, 400.0, 400.0), Vector3(100.0, 100.0, 100.0))
        self.delta_door = 0.005
        self.delta_handle = 0.01
        self.T_W_T = PyKDL.Frame(PyKDL.Vector(0.2,-0.05,0))    # tool transformation
        self.current_max_wrench = Wrench(Vector3(20, 20, 20), Vector3(20, 20, 20))
        self.wrench_emergency_stop = False
        self.exit_on_emergency_stop = True

        # for score function
        self.init_motion_time_left = 3.0
        self.circle_cx = 0
        self.circle_cy = 0
        self.circle_r = 0
        self.failure_reason = "unknown"

#        print "r_a: %s"%(self.learning_r_a)
#        print "k_handle_x: %s"%(self.learning_k_handle_x)
#        print "k_open_y: %s"%(self.learning_k_open_y)

        self.emergency_stop_active = False

        self.resetMarkCounters()

        self.action_trajectory_client = actionlib.SimpleActionClient("/" + self.prefix + "_arm/cartesian_trajectory", CartesianTrajectoryAction)
        self.action_trajectory_client.wait_for_server()

        self.action_tool_client = actionlib.SimpleActionClient("/" + self.prefix + "_arm/tool_trajectory", CartesianTrajectoryAction)
        self.action_tool_client.wait_for_server()

        self.action_impedance_client = actionlib.SimpleActionClient("/" + self.prefix + "_arm/cartesian_impedance", CartesianImpedanceAction)
        self.action_impedance_client.wait_for_server()

        self.pub_trajectory = rospy.Publisher("/"+self.prefix+"_arm/trajectory", CartesianTrajectory)
        self.pub_impedance = rospy.Publisher("/"+self.prefix+"_arm/impedance", CartesianImpedanceTrajectory)
        self.pub_circle = rospy.Publisher("/estimated_circle", QuaternionStamped)
        self.pub_pm = rospy.Publisher("/pm", PointStamped)
        self.pub_pc = rospy.Publisher("/pc", PointStamped)
        self.pub_msg = rospy.Publisher("/message", PointStamped)
        self.pub_msg_id = 0
        self.listener = tf.TransformListener();
        self.br = tf.TransformBroadcaster()

        self.pub_marker = rospy.Publisher('/door_markers', MarkerArray)

        rospy.sleep(1.0)
        
        self.door_makrer_id=3

        self.door_marker_visible = False
        self.door_marker_pose = Pose()

        self.max_tactile_value = 0
        self.max_tactile_index = 0
        self.max_tactile_finger = 0

        print "Requesting pressure sensors info"
        self.pressure_info = self.get_pressure_sensors_info_client()

        self.wrench_tab = []
        self.wrench_tab_index = 0
        self.wrench_tab_len = 4000
        for i in range(0,self.wrench_tab_len):
            self.wrench_tab.append( Wrench(Vector3(), Vector3()) )

        rospy.Subscriber('/ar_pose_marker', AlvarMarkers, self.alvarMarkerCallback)
        rospy.Subscriber('/'+self.prefix+'_hand/BHPressureState', BHPressureState, self.tactileCallback)
        rospy.Subscriber('/'+self.prefix+'_arm/wrench', Wrench, self.wrenchCallback)

    def moveWrist2(self, wrist_frame, t):
        wrist_pose = pm.toMsg(wrist_frame*self.T_W_T)
        self.br.sendTransform(self.PoseToTuple(wrist_pose)[0], self.PoseToTuple(wrist_pose)[1], rospy.Time.now(), "dest", "torso_base")

    def moveWrist(self, wrist_frame, t, max_wrench):
        # we are moving the tool, so: T_B_Wd*T_W_T
        wrist_pose = pm.toMsg(wrist_frame*self.T_W_T)
        self.br.sendTransform(self.PoseToTuple(wrist_pose)[0], self.PoseToTuple(wrist_pose)[1], rospy.Time.now(), "dest", "torso_base")

        action_trajectory_goal = CartesianTrajectoryGoal()
        action_trajectory_goal.trajectory.header.stamp = rospy.Time.now() + rospy.Duration(0.01)
        action_trajectory_goal.trajectory.points.append(CartesianTrajectoryPoint(
        rospy.Duration(t),
        wrist_pose,
        Twist()))
        action_trajectory_goal.wrench_constraint = max_wrench
        self.current_max_wrench = max_wrench
        self.action_trajectory_client.send_goal(action_trajectory_goal)

    def moveTool(self, wrist_frame, t):
        wrist_pose = pm.toMsg(wrist_frame)

        action_tool_goal = CartesianTrajectoryGoal()
        action_tool_goal.trajectory.header.stamp = rospy.Time.now()
        action_tool_goal.trajectory.points.append(CartesianTrajectoryPoint(
        rospy.Duration(t),
        wrist_pose,
        Twist()))
        self.action_tool_client.send_goal(action_tool_goal)

    def moveImpedance(self, k, t):
        action_impedance_goal = CartesianImpedanceGoal()
        action_impedance_goal.trajectory.header.stamp = rospy.Time.now() + rospy.Duration(0.1)
        action_impedance_goal.trajectory.points.append(CartesianImpedanceTrajectoryPoint(
        rospy.Duration(t),
        CartesianImpedance(k,Wrench(Vector3(0.7, 0.7, 0.7),Vector3(0.7, 0.7, 0.7)))))
        self.action_impedance_client.send_goal(action_impedance_goal)

    def stopArm(self):
        if self.action_trajectory_client.gh:
            self.action_trajectory_client.cancel_goal()
        if self.action_tool_client.gh:
            self.action_tool_client.cancel_goal()

    def emergencyStop(self):
        self.moveImpedance(self.k_error, 0.5)
        self.stopArm()
        self.emergency_stop_active = True
        print "emergency stop"

    def emergencyExit(self):
        exit(0)

    def checkStopCondition(self, t=0.0):

        end_t = rospy.Time.now()+rospy.Duration(t+0.0001)
        while rospy.Time.now()<end_t:
            if rospy.is_shutdown():
                self.emergencyStop()
                print "emergency stop: interrupted  %s  %s"%(self.getMaxWrench(), self.wrench_tab_index)
                self.failure_reason = "user_interrupt"
                rospy.sleep(1.0)
                if self.exit_on_emergency_stop:
                    self.emergencyExit()
            if self.wrench_emergency_stop:
                self.emergencyStop()
                print "too big wrench"
                self.failure_reason = "too_big_wrench"
                rospy.sleep(1.0)
                if self.exit_on_emergency_stop:
                    self.emergencyExit()

            if (self.action_trajectory_client.gh) and ((self.action_trajectory_client.get_state()==GoalStatus.REJECTED) or (self.action_trajectory_client.get_state()==GoalStatus.ABORTED)):
                state = self.action_trajectory_client.get_state()
                result = self.action_trajectory_client.get_result()
                self.emergencyStop()
                print "emergency stop: traj_err: %s ; %s ; max_wrench: %s   %s"%(state, result, self.getMaxWrench(), self.wrench_tab_index)
                self.failure_reason = "too_big_wrench_trajectory"
                rospy.sleep(1.0)
                if self.exit_on_emergency_stop:
                    self.emergencyExit()

            if (self.action_tool_client.gh) and ((self.action_tool_client.get_state()==GoalStatus.REJECTED) or (self.action_tool_client.get_state()==GoalStatus.ABORTED)):
                state = self.action_tool_client.get_state()
                result = self.action_tool_client.get_result()
                self.emergencyStop()
                print "emergency stop: tool_err: %s ; %s ; max_wrench: %s   %s"%(state, result, self.getMaxWrench(), self.wrench_tab_index)
                self.failure_reason = "too_big_wrench_tool"
                rospy.sleep(1.0)
                if self.exit_on_emergency_stop:
                    self.emergencyExit()
            rospy.sleep(0.01)
        return self.emergency_stop_active


    def move_hand_client(self, prefix, q):
        rospy.wait_for_service('/' + self.prefix + '_hand/move_hand')
        try:
            move_hand = rospy.ServiceProxy('/' + self.prefix + '_hand/move_hand', BHMoveHand)
            resp1 = move_hand(q[0], q[1], q[2], q[3], 1.2, 1.2, 1.2, 1.2, 2000, 2000, 2000, 2000)
        except rospy.ServiceException, e:
            print "Service call failed: %s"%e

    def estCircle(self, px, py):
      x_m = mean(px)
      y_m = mean(py)
    
      def calc_R(xc, yc):
        """ calculate the distance of each 2D points from the center (xc, yc) """
        return sqrt((px-xc)**2 + (py-yc)**2)

      def f_2(c):
        """ calculate the algebraic distance between the 2D points and the mean circle centered at c=(xc, yc) """
        Ri = calc_R(*c)
        return Ri - Ri.mean()
        
      center_estimate = x_m, y_m
      center_2, ier = optimize.leastsq(f_2, center_estimate)

      xc, yc = center_2
      Ri_2       = calc_R(xc, yc)
      R      = Ri_2.mean()
      return [xc, yc, R]

    def circle(self, cx, cy, r, a):
      dx = math.cos(a) * r
      dy = math.sin(a) * r
      px = cx + dx
      py = cy + dy
      return [px, py]
      
    def interpolate(begin, end, i, lenght):
      return begin + (((end - begin)/lenght)*i)  

    def publishDoorMarker(self, cx, cy, cz, r):
        m = MarkerArray()

        marker = Marker()
        marker.header.frame_id = 'torso_base'
        marker.header.stamp = rospy.Time.now()
        marker.ns = 'door'
        marker.id = 0
        marker.type = 3
        marker.action = 0
        marker.pose.position.x = cx
        marker.pose.position.y = cy
        marker.pose.position.z = cz
        marker.pose.orientation.x = 0.0;
        marker.pose.orientation.y = 0.0;
        marker.pose.orientation.z = 0.0;
        marker.pose.orientation.w = 1.0;
        marker.scale.x = r*2;
        marker.scale.y = r*2;
        marker.scale.z = 0.01;
        marker.color.a = 0.5;
        marker.color.r = 1.0;
        marker.color.g = 0.0;
        marker.color.b = 0.0;
        m.markers.append(marker)

        self.pub_marker.publish(m)

    def publishSinglePointMarker(self, x, y, z, i, r=0.0, g=1.0, b=0.0):
        m = MarkerArray()

        marker = Marker()
        marker.header.frame_id = 'torso_base'
        marker.header.stamp = rospy.Time.now()
        marker.ns = 'door'
        marker.id = i
        marker.type = 1
        marker.action = 0
        marker.pose.position.x = x
        marker.pose.position.y = y
        marker.pose.position.z = z
        marker.pose.orientation.x = 0.0;
        marker.pose.orientation.y = 0.0;
        marker.pose.orientation.z = 0.0;
        marker.pose.orientation.w = 1.0;
        marker.scale.x = 0.005;
        marker.scale.y = 0.005;
        marker.scale.z = 0.005;
        marker.color.a = 0.5;
        marker.color.r = r;
        marker.color.g = g;
        marker.color.b = b;
        m.markers.append(marker)

        self.pub_marker.publish(m)

    def hasContact(self, threshold):
        if self.max_tactile_value>threshold:
            return True
        return False

    def getContactPointFrame(self):
        pt = self.pressure_info.sensor[self.max_tactile_finger].center[self.max_tactile_index]
        T_F_C = PyKDL.Frame(PyKDL.Vector(pt.x, pt.y, pt.z))
        return T_F_C

    def getTransformations(self):
        pose = self.listener.lookupTransform('torso_base', self.prefix+'_arm_7_link', rospy.Time(0))
        self.T_B_W = pm.fromTf(pose)

        pose = self.listener.lookupTransform('/'+self.prefix+'_HandPalmLink', '/'+self.prefix+'_HandFingerThreeKnuckleThreeLink', rospy.Time(0))
        self.T_E_F = pm.fromTf(pose)
        self.T_F_E = self.T_E_F.Inverse()

        self.T_F_C = self.getContactPointFrame()
        self.T_C_F = self.T_F_C.Inverse()

    def stepBackFromHandle(self):
        self.getTransformations()
        print "moving desired pose to current pose"
        self.moveWrist(self.T_B_W, 2.0, Wrench(Vector3(20,20,15), Vector3(6,4,2)))
        self.checkStopCondition(2.0)

        self.getTransformations()
        print "moving gripper outwards the handle"
        T_W_Wd = PyKDL.Frame(PyKDL.Vector(0,-0.05,0))
        T_B_Wd = self.T_B_W*T_W_Wd
        self.moveWrist(T_B_Wd, 0.5, Wrench(Vector3(10,15,10), Vector3(4,3,2)))
        self.checkStopCondition(0.5)

        self.getTransformations()
        print "rotating gripper outwards the handle"
        T_W_Wd = PyKDL.Frame(PyKDL.Rotation.RotZ(-math.pi/8.0))
        T_B_Wd = self.T_B_W*T_W_Wd
        self.moveWrist(T_B_Wd, 2.0, Wrench(Vector3(10,15,10), Vector3(4,3,2)))
        self.checkStopCondition(2.0)

    def openTheDoor(self):
        px = []
        py = []

        self.score_open_A = 1000.0
        self.score_open_B = 800.0

        self.resetMarkCounters()

        self.getTransformations()

        T_E_Ed = PyKDL.Frame(PyKDL.Vector(0, self.r_a, -self.d_init))
        T_B_C_d_init = self.T_B_W*self.T_W_E*T_E_Ed*self.T_E_F*self.T_F_C
        P_d_init = T_B_C_d_init*PyKDL.Vector(0,0,0)

        T_B_C = self.T_B_W*self.T_W_E*self.T_E_F*self.T_F_C
        P_contact = T_B_C*PyKDL.Vector(0,0,0)
        px.append(P_contact.x())
        py.append(P_contact.y())
        pz = P_contact.z()
        P_contact_prev = P_contact
        m_id = 0
        self.publishSinglePointMarker(P_contact.x(), P_contact.y(), P_contact.z(), m_id, 1.0, 0.0, 0.0)
        m_id += 1

        T_B_Wd = self.T_B_W*self.T_W_E*T_E_Ed*self.T_E_W
        self.moveWrist(T_B_Wd, 3.0, Wrench(Vector3(10,20,20), Vector3(3,2,2)))

        lost_contact = False
        init_end_t = rospy.Time.now()+rospy.Duration(3.0)
        init_contact_measure_t = rospy.Time.now()+rospy.Duration(1.0)
        while rospy.Time.now()<init_end_t:
            self.getTransformations()
            T_B_C = self.T_B_W*self.T_W_E*self.T_E_F*self.T_F_C
            P_contact = T_B_C*PyKDL.Vector(0,0,0)
            dist = math.sqrt((P_contact_prev.x()-P_contact.x())*(P_contact_prev.x()-P_contact.x()) + (P_contact_prev.y()-P_contact.y())*(P_contact_prev.y()-P_contact.y()))
            if (dist>0.005):
                px.append(P_contact.x())
                py.append(P_contact.y())
                P_contact_prev = P_contact
                self.publishSinglePointMarker(P_contact.x(), P_contact.y(), P_contact.z(), m_id, 1.0, 0.0, 0.0)
                m_id += 1

            if (rospy.Time.now() > init_contact_measure_t) and (not self.hasContact(50)):
                lost_contact = True

            if lost_contact or self.checkStopCondition(0.01):
                init_dist = math.sqrt((P_contact.x()-px[0])*(P_contact.x()-px[0]) + (P_contact.y()-py[0])*(P_contact.y()-py[0]))
                f = init_dist/self.d_init
                if f>1.0:
                    f = 1.0
                score = (1.0-f)*self.score_open_A + f*self.score_open_B
                # for score function
                dur = init_end_t-rospy.Time.now()
                self.init_motion_time_left = dur.to_sec()
                self.emergencyStop()
                if lost_contact:
                    self.failure_reason = "lost_contact"
                    print "end: lost contact"
                rospy.sleep(1.0)
                return score

        init_dist = math.sqrt((P_contact.x()-px[0])*(P_contact.x()-px[0]) + (P_contact.y()-py[0])*(P_contact.y()-py[0]))
        f = init_dist/self.d_init
        if f>1.0:
#            print "wrong f value: %s"%(f)
            f = 1.0
        score_after_init = (1.0-f)*self.score_open_A + f*self.score_open_B

        print "init motion finished"

        if len(px)>1:
            cx, cy, r = self.estCircle(px, py)
            r_old = r
        else:
            return score_after_init

        # for score function
        self.init_motion_time_left = 0.0
        self.circle_cx = cx
        self.circle_cy = cy
        self.circle_r = r

        return score_after_init

        self.publishDoorMarker(cx, cy, pz, r)
        circle = QuaternionStamped()
        circle.header.frame_id = 'torso_base'
        circle.header.stamp = rospy.Time.now()
        circle.quaternion = Quaternion(cx, cy, pz, r)
        self.pub_circle.publish(circle)
        print "circle: x: %s   y: %s    r: %s"%(cx,cy,r)

        self.getTransformations()
        T_B_C = self.T_B_W*self.T_W_E*self.T_E_F*self.T_F_C
        P_contact = T_B_C*PyKDL.Vector(0,0,0)
        alpha_door = math.atan2(P_contact.y()-cy, P_contact.x()-cx)

        # vector from initial contact point to estimated circle center
        V_p_c = PyKDL.Vector(cx-px[0], cy-py[0], 0)
        # vector pointing to the right side of the door marker
        V_right = self.T_B_M*PyKDL.Vector(1,0,0)

        # for right door the dot product should be positive
        if PyKDL.dot(V_p_c, V_right) < 0:
            print "estimation error: door is not right"
            return     
        if r > 0.45 :
            print "estimation error: too big radius"
            return     
        if r < 0.10 :
            print "estimation error: too small radius"
            return

        alpha_init = math.atan2(py[0]-cy, px[0] - cx)
        alpha_dest = alpha_init + self.alpha_open
        alpha = math.atan2(P_d_init.y()-cy, P_d_init.x()-cx)

        print "alpha_init: %s     alpha: %s     alpha_dest: %s"%(alpha_init/numpy.pi*180.0, alpha/numpy.pi*180.0, alpha_dest/numpy.pi*180.0)

        self.moveImpedance(self.k_open, 0.5)
        self.checkStopCondition(0.6)

        self.getTransformations()
        T_B_C = self.T_B_W*self.T_W_E*self.T_E_F*self.T_F_C
        P_contact = T_B_C*PyKDL.Vector(0,0,0)
        alpha_door_after_init = math.atan2(P_contact.y()-cy, P_contact.x()-cx)

        stiffness_change_panalty = alpha_door-alpha_door_after_init
        if stiffness_change_panalty<0:
            stiffness_change_panalty = 0
        print "stiffness_change_panalty: %s"%(stiffness_change_panalty)

        alpha_door = alpha_door_after_init
        alpha_door_max = math.pi*90.0/180.0

        # TODO: remove this input
        raw_input("Press Enter to continue...")

        self.checkStopCondition()

        alpha_contact_last = math.atan2(py[len(py)-1]-cy, px[len(px)-1]-cx)
        beta = 0
        new_traj_point_period = 0.2
        next_traj_update = rospy.Time.now()
        while (alpha < alpha_dest):

            self.getTransformations()
            T_B_C = self.T_B_W*self.T_W_E*self.T_E_F*self.T_F_C
            P_contact = T_B_C*PyKDL.Vector(0,0,0)
            dist = math.sqrt((P_contact_prev.x()-P_contact.x())*(P_contact_prev.x()-P_contact.x()) + (P_contact_prev.y()-P_contact.y())*(P_contact_prev.y()-P_contact.y()))
            alpha_door = math.atan2(P_contact.y()-cy, P_contact.x()-cx)

            if rospy.Time.now()>next_traj_update:
                alpha += self.delta
                beta += self.delta_e
                if beta>alpha_door-alpha_init:
                    beta = alpha_door-alpha_init
                P_d = PyKDL.Vector(cx, cy, pz) + (r+self.r_a)*PyKDL.Vector(math.cos(alpha), math.sin(alpha), 0)
                T_B_Cd = PyKDL.Frame(P_d-P_d_init)*T_B_C_d_init*PyKDL.Frame(PyKDL.Rotation.RotZ(-beta))                

                T_B_Wd = T_B_Cd*self.T_C_F*self.T_F_E*self.T_E_W
                self.moveWrist(T_B_Wd, new_traj_point_period, Wrench(Vector3(20,20,15), Vector3(6,4,2)))
                Wd = T_B_Wd*PyKDL.Vector()
                self.publishSinglePointMarker(Wd.x(), Wd.y(), Wd.z(), m_id, 0.0, 1.0, 0.0)
                m_id += 1
                next_traj_update = rospy.Time.now() + rospy.Duration(new_traj_point_period)

            if alpha_door-alpha_init<0:
                alpha_door += 2.0 * math.pi

            if alpha_door-alpha_init > alpha_door_max:
                print "door is 90 deg. opened"
                break

            f = (alpha_door - alpha_door_after_init)/(alpha_door_max-(alpha_door_after_init-alpha_init))
            if f>1.0:
#                print "wrong f value: %s"%(f)
                f = 1.0
            if f<0.0:
#                print "wrong f value: %s"%(f)
                f = 0.0
            score = (1.0-f)*score_after_init
#            print "score: %s    alpha_door: %s"%(score, alpha_door)
#            print "score: %s"%(score)

#            T_B_C = self.T_B_W*self.T_W_E*self.T_E_F*self.T_F_C
#            P_contact = T_B_C*PyKDL.Vector(0,0,0)
#            dist = math.sqrt((P_contact_prev.x()-P_contact.x())*(P_contact_prev.x()-P_contact.x()) + (P_contact_prev.y()-P_contact.y())*(P_contact_prev.y()-P_contact.y()))
            if (dist>0.005) and (alpha_contact_last<alpha_door):
                px.append(P_contact.x())
                py.append(P_contact.y())
                P_contact_prev = P_contact
                self.publishSinglePointMarker(P_contact.x(), P_contact.y(), P_contact.z(), m_id, 1.0, 0.0, 0.0)
                m_id += 1
                alpha_contact_last = alpha_door

            cx, cy, r = self.estCircle(px, py)
            r_old = r

            self.publishDoorMarker(cx, cy, pz, r)
            circle = QuaternionStamped()
            circle.header.frame_id = 'torso_base'
            circle.header.stamp = rospy.Time.now()
            circle.quaternion = Quaternion(cx, cy, pz, r)
            self.pub_circle.publish(circle)

            if r > 0.50:
                print "estimation error: too big radius"
                return score+stiffness_change_panalty
            if r < 0.10 :
                print "estimation error: too small radius"
                return score+stiffness_change_panalty

            self.checkStopCondition(0.05)

#            print "alpha: %s   beta: %s"%(alpha*180.0/math.pi, beta*180.0/math.pi)

            if not self.hasContact(50):
                self.emergencyStop()
                print "end: lost contact"
                rospy.sleep(1.0)
                return score+stiffness_change_panalty
        return stiffness_change_panalty

    def moveRelToMarker(self, P, t, max_wrench):
        T_M_Ed = PyKDL.Frame(P)*PyKDL.Frame(PyKDL.Rotation.RotY(math.pi))*PyKDL.Frame(PyKDL.Rotation.RotZ(-math.pi/2.0))
        T_B_Wd = self.T_B_M*T_M_Ed*self.T_E_W
        self.moveWrist(T_B_Wd, t, max_wrench)

    def updateMarkerPose(self, P_door_surface):
        v1 = PyKDL.Vector( P_door_surface[0][0], P_door_surface[0][1], P_door_surface[0][2] )
        v2 = PyKDL.Vector( P_door_surface[1][0], P_door_surface[1][1], P_door_surface[1][2] )
        v3 = PyKDL.Vector( P_door_surface[2][0], P_door_surface[2][1], P_door_surface[2][2] )

        nz = (v1-v2) * (v2-v3)
        nz.Normalize()

        mz = self.T_B_M.M * PyKDL.Vector(0, 0, 1)
        if PyKDL.dot(nz, mz) < 0:
            nz = -nz

        mx = self.T_B_M.M * PyKDL.Vector(1, 0, 0)

        ny = nz * mx
        ny.Normalize()
        nx = ny * nz
        nx.Normalize()

        rot = PyKDL.Rotation(nx, ny, nz)

        dist_m = PyKDL.dot( self.T_B_M.p, nz )
        dist_n = PyKDL.dot( PyKDL.Vector( P_door_surface[0][0], P_door_surface[0][1], P_door_surface[0][2] ), nz )

        m_p = nz*(dist_n-dist_m) + self.T_B_M.p
        frame = PyKDL.Frame( rot, m_p )
        self.T_B_M = frame

    def closeTheDoor(self):
        self.move_hand_client(self.prefix, self.q_close)

        self.moveImpedance(self.k_close, 1.0)

        self.moveRelToMarker(self.P_e1, 3.0, Wrench(Vector3(10,20,10), Vector3(2,2,2)))
        self.checkStopCondition(3.0)

        raw_input("Press Enter to continue...")

        self.moveRelToMarker(self.P_e2, 3.0, Wrench(Vector3(10,20,10), Vector3(2,2,2)))
        self.checkStopCondition(3.0)

        self.moveRelToMarker(self.P_e3, 3.0, Wrench(Vector3(10,20,10), Vector3(2,2,2)))
        self.checkStopCondition(3.0)

        print "changing stiffness to very low value"
        self.moveImpedance(self.k_error, 0.5)
        self.checkStopCondition(1.0)

    def handleEmergencyStop(self):
        if self.emergency_stop_active:
            ch = '_'
            while (ch != 'e') and (ch != 'n') and (ch != 'r'):
                ch = raw_input("Emergency stop active... (e)xit, (n)ext case, (r)epeat case: ")
            if ch == 'e':
                exit(0)
            if ch == 'n':
                self.index += 1
            self.getTransformations()
            print "moving desired pose to current pose"
            self.moveWrist(self.T_B_W, 2.0, Wrench(Vector3(20,20,15), Vector3(6,4,2)))
            self.checkStopCondition(2.0)
            self.emergency_stop_active = False
            return True
        return False

    def printQualityMeasure(self, score_open):
        print "quality measure:"

        print "init_motion_time_left: %s"%(self.init_motion_time_left)
        print "circle_cx: %s"%(self.circle_cx)
        print "circle_cy: %s"%(self.circle_cy)
        print "circle_r: %s"%(self.circle_r)

        wrench_total = math.sqrt(self.wrench_max.force.x*self.wrench_max.force.x + self.wrench_max.force.y*self.wrench_max.force.y + self.wrench_max.force.z*self.wrench_max.force.z) + 10*math.sqrt(self.wrench_max.torque.x*self.wrench_max.torque.x + self.wrench_max.torque.y*self.wrench_max.torque.y + self.wrench_max.torque.z*self.wrench_max.torque.z)
        wrench_mean_total = math.sqrt(self.wrench_mean.force.x*self.wrench_mean.force.x + self.wrench_mean.force.y*self.wrench_mean.force.y + self.wrench_mean.force.z*self.wrench_mean.force.z) + 10*math.sqrt(self.wrench_mean.torque.x*self.wrench_mean.torque.x + self.wrench_mean.torque.y*self.wrench_mean.torque.y + self.wrench_mean.torque.z*self.wrench_mean.torque.z)

        print "total max wrench: %s"%(wrench_total)
        print "total mean wrench: %s"%(wrench_mean_total)
        print "score_open: %s"%(score_open)
        print "total score: %s"%(wrench_total+wrench_mean_total+score_open)
        print "failure_reason: %s"%(self.failure_reason)

        with open("experiments.txt", "a") as exfile:
            exfile.write( "quality measure:" + "\n")
            exfile.write( "init_motion_time_left:" + str(self.init_motion_time_left) + "\n" )
            exfile.write( "circle_cx:" + str(self.circle_cx) + "\n" )
            exfile.write( "circle_cy:" + str(self.circle_cy) + "\n" )
            exfile.write( "circle_r:" + str(self.circle_r) + "\n" )
            exfile.write( "total max wrench:" + str(wrench_total) + "\n" )
            exfile.write( "total mean wrench:" + str(wrench_mean_total) + "\n" )
            exfile.write( "score_open:" + str(score_open) + "\n" )
            exfile.write( "total score:" + str(wrench_total+wrench_mean_total+score_open) + "\n" )
            exfile.write( "failure_reason:" + self.failure_reason + "\n" )

    def spin(self):

        # start with very low stiffness
        print "setting stiffness to very low value"
        self.moveImpedance(self.k_error, 0.5)
        self.checkStopCondition(0.5)

        raw_input("Press Enter to continue...")
        self.checkStopCondition()

        # save current wrist position
        self.listener.waitForTransform('torso_base', self.prefix+'_arm_7_link', rospy.Time.now(), rospy.Duration(4.0))
        pose = self.listener.lookupTransform('torso_base', self.prefix+'_arm_7_link', rospy.Time(0))
        T_B_W = pm.fromTf(pose)

        print "setting the tool to %s relative to wrist frame"%(self.T_W_T)
        # move both tool position and wrist position - the gripper holds its position
        print "moving wrist"
        # we assume that during the initialization there are no contact forces, so we limit the wrench
        self.moveWrist( T_B_W, 2.0, Wrench(Vector3(5, 5, 5), Vector3(2, 2, 2)) )
        print "moving tool"
        self.moveTool( self.T_W_T, 2.0 )
        self.checkStopCondition(2.0)

        # change the stiffness
        print "changing stiffness for door approach"
        self.moveImpedance(self.k_door, 2.0)
        self.checkStopCondition(2.0)

        # straighten fingers
        self.move_hand_client(self.prefix, self.q_start)

        rospy.sleep(2.0)

        door_marker = ((0.8666992082584777, -0.174810766112004, 1.310426812445025), (-0.4667586404443633, 0.5244352551999468, 0.5420385102088775, -0.46184227624204893))

        if door_marker == None:
            if self.door_marker_visible:
                print "Found door marker"
            else:
                self.emergencyStop()
                print "Could not find door marker"
                rospy.sleep(1.0)
                return

            self.checkStopCondition()

            # get door marker absolute position
            self.listener.waitForTransform('torso_base', 'ar_marker_3', rospy.Time.now(), rospy.Duration(4.0))
            door_marker = self.listener.lookupTransform('torso_base', 'ar_marker_3', rospy.Time(0))

        print door_marker
        self.T_B_M = pm.fromTf(door_marker)

        self.listener.waitForTransform(self.prefix+'_arm_7_link', self.prefix+'_HandPalmLink', rospy.Time.now(), rospy.Duration(4.0))
        pose = self.listener.lookupTransform(self.prefix+'_arm_7_link', self.prefix+'_HandPalmLink', rospy.Time(0))
        self.T_W_E = pm.fromTf(pose)
        self.T_E_W = self.T_W_E.Inverse()

        # approach the door
        self.move_hand_client(self.prefix, self.q_door)
        rospy.sleep(0.5)

#        self.moveRelToMarker(self.P_s[0], 1.0, Wrench(Vector3(15,15,15), Vector3(3,3,3)))
#        self.checkStopCondition(1.0)

        P_door_surface = []
        # touch the door surface in three different points
        for i in range(0, 3):
            self.moveRelToMarker(self.P_s[i], 3.0, Wrench(Vector3(15,15,15), Vector3(3,3,3)))
            self.checkStopCondition(3.0)

            print "moved to point P_s"

            d_door = 0.0
            contact_found = False
            while d_door<0.3:
                self.checkStopCondition()
                d_door += self.delta_door
                self.moveRelToMarker(self.P_s[i]+PyKDL.Vector(0, 0, -d_door), 0.25, Wrench(Vector3(10,15,20), Vector3(2,2,2)))
                rospy.sleep(0.125)
                if self.hasContact(100):
                    contact_found = True
                    break
                rospy.sleep(0.1)
                if self.hasContact(100):
                    contact_found = True
                    break

            if contact_found:
                print "Found contact with door"
            else:
                print "Could not reach the door"
                self.emergencyStop()
                rospy.sleep(1.0)
                return

            rospy.sleep(0.5)

            self.getTransformations()
            T_B_C = self.T_B_W * self.T_W_E * self.T_E_F * self.T_F_C
            P_door_surface.append( T_B_C * PyKDL.Vector(0, 0, 0) )

            self.moveRelToMarker(self.P_s[i], 3.0, Wrench(Vector3(15,15,20), Vector3(3,3,3)))
            self.checkStopCondition(3.0)

        print P_door_surface

        print "before:"
        print self.T_B_M
        self.updateMarkerPose(P_door_surface)
        print "after:"
        print self.T_B_M

        # straighten fingers
        self.moveRelToMarker(self.P_s[0], 3.0, Wrench(Vector3(15,15,15), Vector3(3,3,3)))
        self.move_hand_client(self.prefix, self.q_start)
        self.checkStopCondition(2.5)

        self.moveImpedance(self.k_door2, 2.0)
        self.move_hand_client(self.prefix, self.q_handle)
        self.checkStopCondition(2.0)

        self.getTransformations()

        self.T_F_N = PyKDL.Frame( PyKDL.Vector(0.05, 0.01, 0) )
        T_E_N = self.T_E_F * self.T_F_N

        dist_z = (T_E_N * PyKDL.Vector(0, 0, 0)).z()
        print "dist_z: %s"%(dist_z)

        raw_input("Press Enter to continue...")

        # starting point for handle search
        P_handle = PyKDL.Vector(self.P_s[0].x(), self.P_s[0].y(), dist_z)
        self.moveRelToMarker(P_handle, 5.0, Wrench(Vector3(10, 10, 10), Vector3(2, 2, 2)))
        self.checkStopCondition(5.0)
        
#        exit(0)

        # approach handle
        d_handle = 0.0
        contact_found = False
        while d_handle<0.4:
            self.checkStopCondition()
            d_handle += self.delta_handle
            self.moveRelToMarker(P_handle+PyKDL.Vector(-d_handle, 0, 0), 0.25, Wrench(Vector3(10,20,15), Vector3(2,2,2)))
            rospy.sleep(0.125)
            if self.hasContact(100):
                contact_found = True
                break
            rospy.sleep(0.1)
            if self.hasContact(100):
                contact_found = True
                break

        if contact_found:
            print "Found contact with handle"
        else:
            print "Could not reach the handle"
            self.emergencyStop()
            rospy.sleep(1.0)
            return

        raw_input("Press Enter to continue...")

        self.getTransformations()

        T_M_B = self.T_B_M.Inverse()
        T_M_E = T_M_B * self.T_B_W * self.T_W_E

        gripper_handle_pos = T_M_E * PyKDL.Vector(0,0,0)
        print "actual gripper position relative to marker: %s"%(gripper_handle_pos)

        raw_input("Press Enter to continue...")

        self.exit_on_emergency_stop = False

        forces = [4.0, 6.0, 8.0, 10.0] #, 12.0]
        k_x = [200.0, 350.0, 500.0]
        k_y = [20.0, 60.0, 100.0]


        with open("experiments.txt", "a") as exfile:
            exfile.write("******** experiment series begin ********" + "\n")


        self.max_index = len(forces) * len(k_x) * len(k_y)

        self.index = 0
        # door opening loop
        while self.index < self.max_index:
            self.failure_reason = "unknown"

            i = 0
            for forces_v in forces:
                for k_x_v in k_x:
                    for k_y_v in k_y:
                        if i == self.index:
                            self.force = forces_v
                            self.learning_k_handle_x = k_x_v
                            self.learning_k_open_x = k_x_v
                            self.learning_k_open_y = k_y_v
                            self.learning_r_a = self.force / self.learning_k_open_y
                        i += 1

            self.r_a = self.learning_r_a
            self.k_handle = Wrench(Vector3(self.learning_k_handle_x, 35.0, 1000.0), Vector3(300.0, 300.0, 300.0))
            self.k_open = Wrench(Vector3(self.learning_k_open_x, self.learning_k_open_y, 1000.0), Vector3(300.0, 300.0, 300.0))

            print "parameters:"
            print "index: %s"%(self.index)
            print "force: %s"%(self.force)
            print "r_a: %s"%(self.learning_r_a)
            print "k_handle_x: %s"%(self.learning_k_handle_x)
            print "k_open_y: %s"%(self.learning_k_open_y)

            with open("experiments.txt", "a") as exfile:
                exfile.write("parameters:\n")
                exfile.write("index:"+str(self.index) + "\n")
                exfile.write("force:"+str(self.force) + "\n")
                exfile.write("r_a:"+str(self.learning_r_a) + "\n")
                exfile.write("k_handle_x:"+str(self.learning_k_handle_x) + "\n")
                exfile.write("k_open_y:"+str(self.learning_k_open_y) + "\n")

            self.moveImpedance(self.k_door2, 2.0)
            self.checkStopCondition(2.0)

            self.moveRelToMarker(gripper_handle_pos + PyKDL.Vector(0.10, 0.0, 0.05), 3.0, Wrench(Vector3(10,20,15), Vector3(3,3,3)))
            self.checkStopCondition(3.0)

            if self.handleEmergencyStop():
                continue

            raw_input("Press Enter to continue...")

            self.moveRelToMarker(gripper_handle_pos + PyKDL.Vector(-0.01, 0.0, -0.015), 3.0, Wrench(Vector3(10,20,15), Vector3(3,3,3)))
            self.checkStopCondition(3.0)

            if self.handleEmergencyStop():
                continue

            raw_input("Press Enter to continue...")

            print "changing stiffness for handle pushing"

            self.moveImpedance(self.k_handle, 2.0)
            self.checkStopCondition(2.1)

            if self.handleEmergencyStop():
                self.printQualityMeasure(1000)
                continue

            print "pushing the handle"

            self.moveRelToMarker(gripper_handle_pos+PyKDL.Vector(-self.r_a, 0, 0), 3.0, Wrench(Vector3(10,20,10), Vector3(2,2,2)))
            self.checkStopCondition(3.0)

            if self.handleEmergencyStop():
                self.printQualityMeasure(1000)
                continue

            score_open = self.openTheDoor()

            self.printQualityMeasure(score_open)

            if self.handleEmergencyStop():
                continue

            raw_input("Press Enter to stop pulling the handle...")
            self.stepBackFromHandle()

            if self.handleEmergencyStop():
                continue
            raw_input("Press Enter to continue...")

            self.index += 1

#        self.closeTheDoor()

        return

if __name__ == '__main__':
    rospy.init_node('door_opener')
    doorOpener = DoorOpener()

    try:
        doorOpener.spin()
    except rospy.ROSInterruptException: pass
    except IOError: pass
    except KeyError: pass

