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

    def sendNextEvent(self):
        pc = PointStamped()
        pc.header.frame_id = 'torso_base'
        pc.header.stamp = rospy.Time.now()
        pc.point = Point(self.pub_msg_id, 0, 0)
        self.pub_msg.publish(pc)
        self.pub_msg_id += 1

    def __init__(self):
        # parameters
        self.prefix="right"
        self.q_start = (0.0/180.0*numpy.pi, 0.0/180.0*numpy.pi, 0.0/180.0*numpy.pi, 180.0/180.0*numpy.pi) 
        self.q_door = (40.0/180.0*numpy.pi, 40.0/180.0*numpy.pi, 40.0/180.0*numpy.pi, 180.0/180.0*numpy.pi)
        self.q_handle = (75.0/180.0*numpy.pi, 75.0/180.0*numpy.pi, 75.0/180.0*numpy.pi, 180.0/180.0*numpy.pi)
        self.P_s = PyKDL.Vector(0.0, -0.1, 0.3)
        self.r_a = 0.25
        self.d_init = 0.1
        self.alpha_open = 100.0/180.0*numpy.pi
        self.delta = 0.005
        self.delta_e = 0.04
        self.k_door = Wrench(Vector3(600.0, 1000.0, 1000.0), Vector3(300.0, 300.0, 300.0))
        self.k_handle = Wrench(Vector3(500.0, 35.0, 1000.0), Vector3(300.0, 300.0, 300.0))
        self.k_open = Wrench(Vector3(150.0, 35.0, 1000.0), Vector3(300.0, 300.0, 300.0))
        self.k_end = Wrench(Vector3(300.0, 300.0, 1000.0), Vector3(300.0, 300.0, 300.0))
        self.delta_door = 0.005
        self.delta_handle = 0.01

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

        rospy.Subscriber('/ar_pose_marker', AlvarMarkers, self.alvarMarkerCallback)
        rospy.Subscriber('/'+self.prefix+'_hand/BHPressureState', BHPressureState, self.tactileCallback)

    def moveWrist2(self, wrist_frame, t):
        wrist_pose = pm.toMsg(wrist_frame)
        self.br.sendTransform(self.PoseToTuple(wrist_pose)[0], self.PoseToTuple(wrist_pose)[1], rospy.Time.now(), "dest", "torso_base")

    def moveWrist(self, wrist_frame, t):
        wrist_pose = pm.toMsg(wrist_frame)
        self.br.sendTransform(self.PoseToTuple(wrist_pose)[0], self.PoseToTuple(wrist_pose)[1], rospy.Time.now(), "dest", "torso_base")
        trj = CartesianTrajectory()
        trj.header.stamp = rospy.Time.now()
        trj.points.append(CartesianTrajectoryPoint(
        rospy.Duration(t),
        wrist_pose,
        Twist()))
        self.pub_trajectory.publish(trj)

    def moveImpedance(self, k, t):
        trj_imp = CartesianImpedanceTrajectory()
        trj_imp.header.stamp = rospy.Time.now() + rospy.Duration(0.1)
        trj_imp.points.append(CartesianImpedanceTrajectoryPoint(
        rospy.Duration(t),
        CartesianImpedance(k,Wrench(Vector3(0.7, 0.7, 0.7),Vector3(0.7, 0.7, 0.7)))))
        self.pub_impedance.publish(trj_imp)

    def stopArm(self):
        trj = CartesianTrajectory()
        trj.header.stamp = rospy.Time.now()

        self.pub_trajectory.publish(trj)

    def checkEmergencyStop(self, t=0.0):

        if t < 0.001:
            if rospy.is_shutdown():
                self.stopArm()
                exit(0)
        else:
            end_t = rospy.Time.now()+rospy.Duration(t)
            while rospy.Time.now()<end_t:
                if rospy.is_shutdown():
                    self.stopArm()
                    exit(0)
                rospy.sleep(0.1)


    def move_hand_client(self, prefix, q):
        rospy.wait_for_service('/' + self.prefix + '_hand/move_hand')
        try:
            move_hand = rospy.ServiceProxy('/' + self.prefix + '_hand/move_hand', BHMoveHand)
            resp1 = move_hand(q[0], q[1], q[2], q[3], 0.7, 0.7, 0.7, 0.7, 1000, 1000, 1000, 1000)
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

    def openTheDoor(self):
        px = []
        py = []

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
        self.moveWrist(T_B_Wd, 3.0)

        init_end_t = rospy.Time.now()+rospy.Duration(3.0)
        while rospy.Time.now()<init_end_t:
            self.checkEmergencyStop()
            self.getTransformations()
            T_B_C = self.T_B_W*self.T_W_E*self.T_E_F*self.T_F_C
            P_contact = T_B_C*PyKDL.Vector(0,0,0)
            dist = math.sqrt((P_contact_prev.x()-P_contact.x())*(P_contact_prev.x()-P_contact.x()) + (P_contact_prev.y()-P_contact.y())*(P_contact_prev.y()-P_contact.y()))
            if (dist>0.005) and (dist<0.01):
                px.append(P_contact.x())
                py.append(P_contact.y())
                P_contact_prev = P_contact
                self.publishSinglePointMarker(P_contact.x(), P_contact.y(), P_contact.z(), m_id, 1.0, 0.0, 0.0)
                m_id += 1
            if dist>=0.01:
                print "distance error"

            rospy.sleep(0.01)

        print "init motion finished"

        cx, cy, r = self.estCircle(px, py)

        self.publishDoorMarker(cx, cy, pz, r)
        circle = QuaternionStamped()
        circle.header.frame_id = 'torso_base'
        circle.header.stamp = rospy.Time.now()
        circle.quaternion = Quaternion(cx, cy, pz, r)
        self.pub_circle.publish(circle)
        print "circle: x: %s   y: %s    r: %s"%(cx,cy,r)

        if r > 0.45 :
          return     
        if r < 0.10 :
          return

        alpha_init = math.atan2(py[0]-cy, px[0] - cx)
        alpha_dest = alpha_init + self.alpha_open
        alpha = math.atan2(P_d_init.y()-cy, P_d_init.x()-cx)

        print "alpha_init: %s     alpha: %s     alpha_dest: %s"%(alpha_init/numpy.pi*180.0, alpha/numpy.pi*180.0, alpha_dest/numpy.pi*180.0)

        self.moveImpedance(self.k_open, 3.0)
        self.checkEmergencyStop(3.0)

        raw_input("Press Enter to continue...")

        self.checkEmergencyStop()

        alpha_contact_last = math.atan2(py[len(py)-1]-cy, px[len(px)-1]-cx)
        # 8
        self.sendNextEvent()
        beta = 0
        while (alpha < alpha_dest):
            self.checkEmergencyStop()

            alpha_door = math.atan2(P_contact.y()-cy, P_contact.x()-cx)
            alpha += self.delta
            beta += self.delta_e
            if beta>alpha_door-alpha_init:
                beta = alpha_door-alpha_init
            P_d = PyKDL.Vector(cx, cy, pz) + (r+self.r_a)*PyKDL.Vector(math.cos(alpha), math.sin(alpha), 0)
            T_B_Cd = PyKDL.Frame(P_d-P_d_init)*T_B_C_d_init*PyKDL.Frame(PyKDL.Rotation.RotZ(-beta))

            self.getTransformations()
            T_B_C = self.T_B_W*self.T_W_E*self.T_E_F*self.T_F_C
            P_contact = T_B_C*PyKDL.Vector(0,0,0)
            dist = math.sqrt((P_contact_prev.x()-P_contact.x())*(P_contact_prev.x()-P_contact.x()) + (P_contact_prev.y()-P_contact.y())*(P_contact_prev.y()-P_contact.y()))
            if (dist>0.005) and (dist<0.02) and (alpha_contact_last<alpha_door):
                px.append(P_contact.x())
                py.append(P_contact.y())
                P_contact_prev = P_contact
                self.publishSinglePointMarker(P_contact.x(), P_contact.y(), P_contact.z(), m_id, 1.0, 0.0, 0.0)
                m_id += 1
                alpha_contact_last = alpha_door

            T_B_Wd = T_B_Cd*self.T_C_F*self.T_F_E*self.T_E_W
            self.moveWrist(T_B_Wd, 1.0)

            cx, cy, r = self.estCircle(px, py)

            self.publishDoorMarker(cx, cy, pz, r)
            circle = QuaternionStamped()
            circle.header.frame_id = 'torso_base'
            circle.header.stamp = rospy.Time.now()
            circle.quaternion = Quaternion(cx, cy, pz, r)
            self.pub_circle.publish(circle)

            if r > 0.50:
                print "too big radius"
                break
            if r < 0.10 :
                print "too small radius"
                break

            rospy.sleep(0.1)

            if not self.hasContact(50):
                print "end: no contact"
                return

        raw_input("Press Enter to continue...")

        self.getTransformations()
        self.moveWrist(self.T_B_W, 4.0)
        self.checkEmergencyStop(4.0)
        self.getTransformations()

        T_W_Wd = PyKDL.Frame(PyKDL.Vector(0,-0.05,0))
        T_B_Wd = self.T_B_W*T_W_Wd
        self.moveWrist(T_B_Wd, 1.0)
        self.checkEmergencyStop(1.0)

        T_W_Wd = PyKDL.Frame(PyKDL.Rotation.RotZ(-math.pi/4.0))
        T_B_Wd = self.T_B_W*T_W_Wd
        self.moveWrist(T_B_Wd, 3.0)
        self.checkEmergencyStop(3.0)

        raw_input("Press Enter to continue...")
        self.moveImpedance(self.k_end, 3.0)
        self.checkEmergencyStop(3.0)


    def moveRelToMarker(self, P, t):
        T_M_Ed = PyKDL.Frame(P)*PyKDL.Frame(PyKDL.Rotation.RotY(math.pi))*PyKDL.Frame(PyKDL.Rotation.RotZ(-math.pi/2.0))
        T_B_Wd = self.T_B_M*T_M_Ed*self.T_E_W
        self.moveWrist(T_B_Wd, t)

    def spin(self):

        # straighten fingers
        self.move_hand_client(self.prefix, self.q_start)

        rospy.sleep(1)
        if self.door_marker_visible:
            print "Found door marker"
        else:
            print "Could not find door marker"
            return

        self.checkEmergencyStop()

        # get door marker absolute position
        self.listener.waitForTransform('torso_base', 'ar_marker_3', rospy.Time.now(), rospy.Duration(4.0))
        door_marker = self.listener.lookupTransform('torso_base', 'ar_marker_3', rospy.Time(0))
        self.T_B_M = pm.fromTf(door_marker)

        self.listener.waitForTransform(self.prefix+'_arm_7_link', self.prefix+'_HandPalmLink', rospy.Time.now(), rospy.Duration(4.0))
        pose = self.listener.lookupTransform(self.prefix+'_arm_7_link', self.prefix+'_HandPalmLink', rospy.Time(0))
        self.T_W_E = pm.fromTf(pose)
        self.T_E_W = self.T_W_E.Inverse()

        # set impedence parameters
        self.moveImpedance(self.k_door, 3.0)
        self.checkEmergencyStop(3.0)

        # approach the door
        self.move_hand_client(self.prefix, self.q_door)
        rospy.sleep(0.5)

        self.moveRelToMarker(self.P_s, 5.0)
        self.checkEmergencyStop(5.0)

        # 0
        self.sendNextEvent()

        d_door = 0.0
        contact_found = False
        while d_door<0.2:
            self.checkEmergencyStop()
            d_door += self.delta_door
            self.moveRelToMarker(self.P_s+PyKDL.Vector(0, 0, -d_door), 0.25)
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
            return

        # 1
        self.sendNextEvent()

        # hand configuration change
        print "Going back 8cm"
        d_door -= 0.08
        self.moveRelToMarker(self.P_s+PyKDL.Vector(0, 0, -d_door), 4.0)
        self.checkEmergencyStop(4.0)

        self.move_hand_client(self.prefix, self.q_handle)

        self.checkEmergencyStop(1.0)

        print "Going forward 55cm"
        d_door += 0.055
        self.moveRelToMarker(self.P_s+PyKDL.Vector(0, 0, -d_door), 3.0)
        self.checkEmergencyStop(3.0)

        # approach handle
        d_handle = 0.0
        contact_found = False
        while d_handle<0.4:
            self.checkEmergencyStop()
            d_handle += self.delta_handle
            self.moveRelToMarker(self.P_s+PyKDL.Vector(-d_handle, 0, -d_door), 0.25)
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
            return

        # 3
        self.sendNextEvent()

        raw_input("Press Enter to continue...")

        self.checkEmergencyStop()

        # 4
        self.sendNextEvent()

        if rospy.is_shutdown():
            return

        self.moveImpedance(self.k_handle, 3.0)
        self.checkEmergencyStop(3.0)
        if rospy.is_shutdown():
            return

        # 5
        self.sendNextEvent()

        d_handle += self.r_a
        self.moveRelToMarker(self.P_s+PyKDL.Vector(-d_handle, 0, -d_door), 4.0)
        self.checkEmergencyStop(4.0)

        # 6
        self.sendNextEvent()

        self.openTheDoor()
        return

if __name__ == '__main__':
    rospy.init_node('door_opener')
    doorOpener = DoorOpener()

    try:
        doorOpener.spin()
    except rospy.ROSInterruptException: pass
    except IOError: pass
    except KeyError: pass

