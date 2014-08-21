#!/usr/bin/env python

# Copyright (c) 2014, Robot Control and Pattern Recognition Group, Warsaw University of Technology
# All rights reserved.
# 
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the Warsaw University of Technology nor the
#       names of its contributors may be used to endorse or promote products
#       derived from this software without specific prior written permission.
# 
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
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
from sensor_msgs.msg import *
from geometry_msgs.msg import *
from barrett_hand_controller_srvs.msg import *
from barrett_hand_controller_srvs.srv import *
from cartesian_trajectory_msgs.msg import *
from visualization_msgs.msg import *
import actionlib
from actionlib_msgs.msg import *
from threading import Lock

import tf
from tf import *
from tf.transformations import * 
import tf_conversions.posemath as pm
from tf2_msgs.msg import *

import PyKDL
import math
from numpy import *
import numpy as np
import copy
import matplotlib.pyplot as plt
import thread
from scipy import optimize

from velma import Velma

# reference frames:
# B - robot's base
# R - camera
# W - wrist
# E - gripper
# F - finger distal link
# T - tool
# C - current contact point
# N - the end point of finger's nail
# J - jar marker frame (jar cap)

class MarkerPublisher:
    def __init__(self):
        self.pub_marker = rospy.Publisher('/velma_markers', MarkerArray)

    def publishSinglePointMarker(self, pt, i, r=1, g=0, b=0, namespace='default', frame_id='torso_base', m_type=Marker.CUBE, scale=Vector3(0.005, 0.005, 0.005)):
        m = MarkerArray()
        marker = Marker()
        marker.header.frame_id = frame_id
        marker.header.stamp = rospy.Time.now()
        marker.ns = namespace
        marker.id = i
        marker.type = m_type
        marker.action = 0
        marker.pose = Pose( Point(pt.x(),pt.y(),pt.z()), Quaternion(0,0,0,1) )
        marker.scale = scale
        marker.color = ColorRGBA(r,g,b,0.5)
        m.markers.append(marker)
        self.pub_marker.publish(m)

    def publishMultiPointsMarker(self, pt, r=1, g=0, b=0, namespace='default', frame_id='torso_base', m_type=Marker.CUBE, scale=Vector3(0.002, 0.002, 0.002)):
        m = MarkerArray()
        for i in range(0, len(pt)):
            marker = Marker()
            marker.header.frame_id = frame_id
            marker.header.stamp = rospy.Time.now()
            marker.ns = namespace
            marker.id = i
            marker.type = m_type
            marker.action = 0
            marker.pose = Pose( Point(pt[i].x(),pt[i].y(),pt[i].z()), Quaternion(0,0,0,1) )
            marker.scale = scale
            marker.color = ColorRGBA(r,g,b,0.5)
            m.markers.append(marker)
        self.pub_marker.publish(m)

    def publishVectorMarker(self, v1, v2, i, r, g, b, frame='torso_base', namespace='default'):
        m = MarkerArray()
        marker = Marker()
        marker.header.frame_id = frame
        marker.header.stamp = rospy.Time.now()
        marker.ns = namespace
        marker.id = i
        marker.type = Marker.ARROW
        marker.action = 0
        marker.points.append(Point(v1.x(), v1.y(), v1.z()))
        marker.points.append(Point(v2.x(), v2.y(), v2.z()))
        marker.pose = Pose( Point(0,0,0), Quaternion(0,0,0,1) )
        marker.scale = Vector3(0.001, 0.002, 0)
        marker.color = ColorRGBA(r,g,b,0.5)
        m.markers.append(marker)
        self.pub_marker.publish(m)

    def publishFrameMarker(self, T, base_id, scale=0.1, frame='torso_base', namespace='default'):
        self.publishVectorMarker(T*PyKDL.Vector(), T*PyKDL.Vector(scale,0,0), base_id, 1, 0, 0, frame, namespace)
        self.publishVectorMarker(T*PyKDL.Vector(), T*PyKDL.Vector(0,scale,0), base_id+1, 0, 1, 0, frame, namespace)
        self.publishVectorMarker(T*PyKDL.Vector(), T*PyKDL.Vector(0,0,scale), base_id+2, 0, 0, 1, frame, namespace)
        return base_id+3

def getAngle(v1, v2):
    return math.atan2((v1*v2).Norm(), PyKDL.dot(v1,v2))

class Jar:

    def generatePoints(self, distance):
        self.pt = []
        # side surface
        L = 2.0 * math.pi * self.R
        L_count = int( L/distance )
        H_count = int( self.H/distance )
        for l in range(0, L_count):
            for h in range(1, H_count):
               angle = 2.0*math.pi*float(l)/L_count
               self.pt.append(PyKDL.Vector(self.R*math.cos(angle), self.R*math.sin(angle), self.H*float(h)/H_count)) 
        # top and bottom surface
#        R_count = int( self.R/distance )
#        for r in range(0, R_count+1):
#            current_r = (float(r)/R_count)*self.R
#            L = 2.0*math.pi*current_r
#            L_count = int( L/distance ) + 1
#            for l in range(0, L_count):
#               angle = 2.0*math.pi*float(l)/L_count
#               self.pt.append(PyKDL.Vector(current_r*math.cos(angle), current_r*math.sin(angle), 0.0)) 
#               self.pt.append(PyKDL.Vector(current_r*math.cos(angle), current_r*math.sin(angle), self.H)) 

    def __init__(self, pub_marker = None):
        self.pub_marker = pub_marker
        self.R = 0.04
        self.H = 0.195
        self.generatePoints(0.01)
        self.T_B_Jbase = PyKDL.Frame(PyKDL.Vector(0,0,0))
        self.T_Jbase_Jmarker = PyKDL.Frame(PyKDL.Vector(0,0,self.H))
        self.T_Jmarker_Jbase = self.T_Jbase_Jmarker.Inverse()
        self.position_error = 5.0   # in meters: 5.0m -> "there is a jar somewhere in this room"
        self.resetContactObservations()

    def drawPoints(self):
        print "drawPoints: %s"%(len(self.pt))
        if self.pub_marker != None:
            self.pub_marker.publishMultiPointsMarker(self.pt, 0, 1, 0, namespace="jar_points", frame_id="jar")

    def publishTf(self):
        pose = pm.toMsg(self.T_B_Jbase)
        br.sendTransform([pose.position.x, pose.position.y, pose.position.z], [pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w], rospy.Time.now(), "jar", "torso_base")

    def tfBroadcasterLoop(self, interval, *args):
        while not rospy.is_shutdown():
            self.publishTf()
            self.drawJar()
            rospy.sleep(interval)

    def drawJar(self):
        if self.pub_marker != None:
            self.pub_marker.publishSinglePointMarker(PyKDL.Vector(0,0,self.H*0.5), 0, r=0, g=1, b=0, namespace='jar', frame_id='jar', m_type=Marker.CYLINDER, scale=Vector3(self.R*2.0, self.R*2.0, self.H))

    def addMarkerObservation(self, T_B_M):
        self.position_error = 0.05   # in meters: 0.05m -> "there is a jar somewhere around this marker"
        self.T_B_Jbase = T_B_M * self.T_Jmarker_Jbase

    def resetContactObservations(self):
        self.contacts_Jbase = []

    def addContactObservation(self, pt_B):
        pt_Jbase = self.T_B_Jbase.Inverse() * pt_B
        self.contacts_Jbase.append(copy.copy(pt_Jbase))

    def drawContactObservations(self):
        print "drawContactObservations: %s"%(len(self.contacts_Jbase))
        if self.pub_marker != None:
            self.pub_marker.publishMultiPointsMarker(self.contacts_Jbase, 1, 0, 0, namespace="jar_obs", frame_id="jar")

    def estPosition(self):
        def calc_R(xo, yo):
            ret = []
            """ calculate the minimum distance of each contact point from jar surface pt """
            o = PyKDL.Vector(xo, yo, 0)
            for contact in self.contacts_Jbase:
                contact_o = contact + o
                min_dist = 1000000.0
                for p in self.pt:
                    dist = (contact_o-p).Norm()
                    if dist < min_dist:
                        min_dist = dist
                #ret.append( math.sqrt(min_dist) )
                ret.append( min_dist )
            return numpy.array(ret)
        
        def f_2(c):
            """ calculate the algebraic distance between each contact point and jar surface pt """
            Di = calc_R(*c)
            return Di

        position_estimate = 0.0, 0.0#, 0.0
        position_2, ier = optimize.leastsq(f_2, position_estimate, maxfev = 1000)

        return PyKDL.Vector(position_2[0], position_2[1],0)

    def processContactObservations(self):
        position = self.estPosition()
        print position
        for i in range(0, len(self.contacts_Jbase)):
            self.contacts_Jbase[i] += position
        self.T_B_Jbase = copy.deepcopy( self.T_B_Jbase * PyKDL.Frame(-position) )

    def processContactObservationsForTop(self):
        if len(self.contacts_Jbase) < 1:
            return
        max_z = 0.0
        for i in range(0, len(self.contacts_Jbase)):
            if self.contacts_Jbase[i].z() > max_z:
                max_z = self.contacts_Jbase[i].z()
        position = PyKDL.Vector(0,0,self.H-max_z)
#        print "processContactObservationsForTop: position: %s"%(position)
        for i in range(0, len(self.contacts_Jbase)):
#            print "processContactObservationsForTop: self.contacts_Jbase[%s]: %s"%(i,self.contacts_Jbase[i])
            self.contacts_Jbase[i] += position
#            print "processContactObservationsForTop: self.contacts_Jbase[%s]: %s"%(i,self.contacts_Jbase[i])
        self.T_B_Jbase = copy.deepcopy( self.T_B_Jbase * PyKDL.Frame(-position) )

    def getJarCapFrame(self):
        return self.T_B_Jbase * self.T_Jbase_Jmarker

class JarOpener:
    """
Class for opening the jar.
"""

    def __init__(self, pub_marker=None):
        self.pub_marker = pub_marker
        self.listener = tf.TransformListener();
        self.joint_states_lock = Lock()

    def getJarMarkerPose(self):
        try:
            self.listener.waitForTransform('torso_base', 'ar_marker_0', rospy.Time.now(), rospy.Duration(4.0))
            jar_marker = self.listener.lookupTransform('torso_base', 'ar_marker_0', rospy.Time(0))
        except:
            return None
        return pm.fromTf(jar_marker)

    def resetGripper(self, robot):
        robot.move_hand_client("right", (0.0/180.0*numpy.pi, 0.0/180.0*numpy.pi, 0.0/180.0*numpy.pi, 0.0/180.0*numpy.pi) )
#        self.q_start = (0.0/180.0*numpy.pi, 0.0/180.0*numpy.pi, 0.0/180.0*numpy.pi, 180.0/180.0*numpy.pi)
        if robot.checkStopCondition(3.0):
            exit(0)

    def testHandKinematics(self, robot):
        robot.move_hand_client("right", (0.0/180.0*numpy.pi, 0.0/180.0*numpy.pi, 0.0/180.0*numpy.pi, 40.0/180.0*numpy.pi) )
        if robot.checkStopCondition(3.0):
            exit(0)
        robot.updateTransformations()

        angle = -10.0
        while angle < 180.0:
            T_E_Fd = robot.get_T_E_Fd(0, math.pi*angle/180.0)
            pt = robot.T_B_W * robot.T_W_E * T_E_Fd * PyKDL.Vector(0.05, -0.01, 0)
            if self.pub_marker != None:
                self.pub_marker.publishSinglePointMarker(pt, 0, r=1, g=0, b=0, namespace='default', frame_id='torso_base', m_type=Marker.CUBE, scale=Vector3(0.005, 0.005, 0.005))

            T_E_Fd = robot.get_T_E_Fd(1, math.pi*angle/180.0)
            pt = robot.T_B_W * robot.T_W_E * T_E_Fd * PyKDL.Vector(0.05, -0.01, 0)
            if self.pub_marker != None:
                self.pub_marker.publishSinglePointMarker(pt, 1, r=1, g=0, b=0, namespace='default', frame_id='torso_base', m_type=Marker.CUBE, scale=Vector3(0.005, 0.005, 0.005))

            T_E_Fd = robot.get_T_E_Fd(2, math.pi*angle/180.0)
            pt = robot.T_B_W * robot.T_W_E * T_E_Fd * PyKDL.Vector(0.05, -0.01, 0)
            if self.pub_marker != None:
                self.pub_marker.publishSinglePointMarker(pt, 2, r=1, g=0, b=0, namespace='default', frame_id='torso_base', m_type=Marker.CUBE, scale=Vector3(0.005, 0.005, 0.005))
            if robot.checkStopCondition(0.02):
                exit(0)
            angle += 0.5                

    def collectGripperKinematics(self, robot):
        if False:
            # reset the gripper
            self.resetGripper(robot)
            # get finger tip trajectory during finger movement
            robot.getFingersKinematics()
            # reset the gripper
            self.resetGripper(robot)
            tabs = [robot.F1_kinematics, robot.F2_kinematics, robot.F3_kinematics]
            for t in tabs:
                print "self.FX_kinematics=["
                for data in t:
                    q = data[1].M.GetQuaternion()
                    p = data[1].p
                    print "[%s,PyKDL.Frame(PyKDL.Rotation.Quaternion(%s,%s,%s,%s),PyKDL.Vector(%s,%s,%s))],"%(data[0], q[0], q[1], q[2], q[3], p.x(), p.y(), p.z() )
                print "]"
            exit(0)

    def resetContacts(self):
         self.contacts = []

    def addContact(self, P_contact):
        if len(self.contacts) > 0:
            min_dist = 1000000.0
            for c in self.contacts:
                dist = (c-P_contact).Norm()
                if dist < min_dist:
                    min_dist = dist
            if min_dist > 0.002:
                self.contacts.append(P_contact)
        else:
            self.contacts.append(P_contact)

    def jointStatesCallback(self, data):
        if len(data.name) == 16:
            if data.name[7] == 'right_arm_5_joint':
                self.joint_states_lock.acquire()
                self.q5 = data.position[7]
                self.joint_states_lock.release()

    def spin(self):

        # create the jar model
        jar = Jar(self.pub_marker)
        # start thread for jar tf publishing and for visualization
        thread.start_new_thread(jar.tfBroadcasterLoop, (0.5, 1))
        # look for jar marker
        T_B_J = self.getJarMarkerPose()
        if T_B_J == None:
            print "Cound not find jar marker."
            exit(0)
        # jar marker is found, add observation to the jar model
        print "Found jar marker."
        jar.addMarkerObservation(T_B_J)

        # calculate angle between jar_axis and vertical vector (z) in B
        jar_up_angle = 180.0*getAngle(PyKDL.Frame(T_B_J.M)*PyKDL.Vector(0,0,1), PyKDL.Vector(0,0,1))/math.pi
        print "angle between jar_axis and vertical vector (z) in B: %s deg."%(jar_up_angle)

        # stiffness for jar touching
        k_jar_touching = Wrench(Vector3(1200.0, 1200.0, 1200.0), Vector3(300.0, 300.0, 300.0))
        k_jar_cap_gripping = Wrench(Vector3(1200.0, 1200.0, 1200.0), Vector3(300.0, 300.0, 300.0))
        k_jar_cap_rotating = Wrench(Vector3(100.0, 100.0, 1200.0), Vector3(300.0, 300.0, 300.0))

        # create the robot interface
        velma = Velma()

        velma.updateTransformations()

        spread_angle_cap_deg = 70.0

        # reset the gripper
        self.resetGripper(velma)

        # calculate the best grip for the jar cap
        if True:
            # prepare hook gripper configuration
            velma.move_hand_client("right", (0.0/180.0*numpy.pi, 0.0/180.0*numpy.pi, 0.0/180.0*numpy.pi, spread_angle_cap_deg/180.0*numpy.pi) )
            if velma.checkStopCondition(4.0):
                exit(0)

            velma.updateTransformations()

            # we move the jar along y axis i E frame
            # search for such configuration, that every finger touches the jar in the central plane of the finger
            best_n = 1000.0
            x = 0.0
            for y in np.arange(-0.04, 0.04, 0.001):
                kinematics = [velma.F1_kinematics, velma.F2_kinematics, velma.F3_kinematics]
                finger_index = 0
                contact = [False, False, False]
                desired_angles = [0.0, 0.0, 0.0]
                pt = [PyKDL.Vector(), PyKDL.Vector(), PyKDL.Vector()]
                T_E_Fd = [PyKDL.Frame(), PyKDL.Frame(), PyKDL.Frame()]
                # for each finger iterate through joint angles until there is a contact with the jar
                for k in kinematics:
                    # calculate contact points we want to reach
                    for data in k:
                        desired_angles[finger_index] = data[0]
                        T_E_Fd[finger_index] = velma.get_T_E_Fd(finger_index, data[0])
                        # iterate through all cells of the sensor matrix
                        for T_F_S in velma.pressure_frames:
                            pt[finger_index] = T_E_Fd[finger_index] * T_F_S * PyKDL.Vector()
                            z = pt[finger_index].z()
                            r = (pt[finger_index]-PyKDL.Vector(x,y,z)).Norm()
                            if r <= jar.R:
                                contact[finger_index] = True
                                break
                        if contact[finger_index]:
                            break
                    # if we do not have contact for one finger, discard the whole try
                    if not contact[finger_index]:
                        break
                    finger_index += 1
                # if we have contact point for each finger, compute the plane for three points and its normal
                if contact[0] and contact[1] and contact[2]:
                    center_E = PyKDL.Vector(x,y,0)
                    center_F = T_E_Fd[0].Inverse() * center_E
                    n = math.fabs(center_F.z())
                    center_F = T_E_Fd[1].Inverse() * center_E
                    n += math.fabs(center_F.z())
                    center_F = T_E_Fd[2].Inverse() * center_E
                    n += math.fabs(center_F.z())
                    if n < best_n:
                        best_n = n
                        best_y = y
                        best_pt = copy.deepcopy(pt)
                        best_desired_angles = copy.deepcopy(desired_angles)

            print "best_desired_angles (rad): %s"%(best_desired_angles)
            print "best_y: %s"%(best_y)
            print "best_n: %s"%(best_n)

            # the normal is the z versor of the new frame C
            Cz_inE = (best_pt[0]-best_pt[1])*(best_pt[0]-best_pt[2])
            if Cz_inE.z() < 0.0:
                Cz_inE = -Cz_inE
            Cx_inE = PyKDL.Vector(1,0,0)
            Cy_inE = Cz_inE * Cx_inE
            Cx_inE = Cy_inE * Cz_inE
            Cx_inE.Normalize()
            Cy_inE.Normalize()
            Cz_inE.Normalize()
            Cp_inE = PyKDL.Vector(x,best_y,((best_pt[0]+best_pt[1]+best_pt[2])*(1.0/3.0)).z())
            T_E_JCdecap = PyKDL.Frame( PyKDL.Rotation(Cx_inE, Cy_inE, Cz_inE), Cp_inE)
            T_JCdecap_E = T_E_JCdecap.Inverse()
            cap_hangle_q = copy.deepcopy(best_desired_angles)

        # calculate the best grip for the jar touching
        if True:
            # prepare hook gripper configuration
            velma.move_hand_client("right", (0.0/180.0*numpy.pi, 0.0/180.0*numpy.pi, 0.0/180.0*numpy.pi, 90.0/180.0*numpy.pi) )
            if velma.checkStopCondition(4.0):
                exit(0)

            velma.updateTransformations()

            # we move the jar along y axis i E frame
            # search for such configuration, that every finger touches the jar in the central plane of the finger
            best_n = 1000.0
            x = 0.0
            y = 0.0
            kinematics = [velma.F1_kinematics, velma.F2_kinematics, velma.F3_kinematics]
            finger_index = 0
            contact = [False, False, False]
            desired_angles = [0.0, 0.0, 0.0]
            pt = [PyKDL.Vector(), PyKDL.Vector()]
            T_E_Fd = [PyKDL.Frame(), PyKDL.Frame()]
            # for 2 fingers iterate through joint angles until there is a contact with the jar
            for k in kinematics[0:2]:
                # calculate contact points we want to reach
                for data in k:
                    desired_angles[finger_index] = data[0]
                    T_E_Fd[finger_index] = velma.get_T_E_Fd(finger_index, data[0])
                    # iterate through all cells of the sensor matrix
                    for T_F_S in velma.pressure_frames:
                        pt[finger_index] = T_E_Fd[finger_index] * T_F_S * PyKDL.Vector()
                        z = pt[finger_index].z()
                        r = (pt[finger_index]-PyKDL.Vector(x,y,z)).Norm()
                        if r <= jar.R:
                            contact[finger_index] = True
                            break
                    if contact[finger_index]:
                        break
                finger_index += 1
            # if we have contact point for each finger, compute the middle point for two points
            if contact[0] and contact[1]:
                center_pt = (pt[0] + pt[1]) * 0.5

            # the normal is the z versor of the new frame C
            Cz_inE = PyKDL.Vector(0,0,1)
            Cx_inE = PyKDL.Vector(1,0,0)
            Cy_inE = Cz_inE * Cx_inE
            Cx_inE = Cy_inE * Cz_inE
            Cx_inE.Normalize()
            Cy_inE.Normalize()
            Cz_inE.Normalize()
            Cp_inE = center_pt
            T_E_JC_side_touch = PyKDL.Frame( PyKDL.Rotation(Cx_inE, Cy_inE, Cz_inE), Cp_inE)
            T_JC_E_side_touch = T_E_JC_side_touch.Inverse()

        # start with very low stiffness
        print "setting stiffness to very low value"
        velma.moveImpedance(velma.k_error, 0.5)
        if velma.checkStopCondition(0.5):
            exit(0)

        raw_input("Press Enter to continue...")
        if velma.checkStopCondition():
            exit(0)

        velma.updateTransformations()
        velma.updateAndMoveTool( velma.T_W_E, 2.0 )
        if velma.checkStopCondition(2.0):
            exit(0)

        raw_input("Press Enter to continue...")
        print "setting stiffness to bigger value"

        velma.moveImpedance(k_jar_touching, 5.0)
        if velma.checkStopCondition(5.0):
            exit(0)

        # get contact points observations
        # we want to touch the jar's cap with the middle of the 5th row of tactile matrix
        if True:
            # set hook gripper configuration for one finger (middle - 3rd)
            velma.move_hand_client("right", (0.0/180.0*numpy.pi, 0.0/180.0*numpy.pi, 10.0/180.0*numpy.pi, 180.0/180.0*numpy.pi) )
            if velma.checkStopCondition(3.0):
                exit(0)

            velma.updateTransformations()

            # we want to touch the jar's cap with the middle of the 5th row of tactile matrix
            tactile_row = 4
            # S is the tactile sensor frame
            T_F_S = velma.pressure_frames[tactile_row*3 + 1]
            T_S_F = T_F_S.Inverse()

            # JC is the jar cap frame
            T_B_JC = copy.deepcopy(jar.getJarCapFrame())

            # we assume that S_z = -JC.z
            # we have to choose the best rotation about the JC.z axis
            # lets have the first guess (rotate JC about JC.x axis by 180 deg. to get desired S frame)
            T_B_Sd = T_B_JC * PyKDL.Frame(PyKDL.Rotation.RotX(180.0/180.0*math.pi))

            # then, we search for the best angle about S.Z axis for jar cap approach
            # iterate through angles
            best_score = 1000000.0
            best_angle_deg = 0.0
            velma.updateTransformations()
            T_B_E = velma.T_B_W * velma.T_W_E
            
            for angle_deg in np.arange(0.0, 360.0, 10.0):
                success = True
                total_score = 0.0
                print "angle_deg: %s"%(angle_deg)
                # simulate the approach
                for pos in np.arange(-0.05, 0.05, 0.01):
                    # calculate the transform
                    T_B_Ed = T_B_Sd * PyKDL.Frame(PyKDL.Rotation.RotZ(angle_deg/180.0*math.pi)) * PyKDL.Frame(PyKDL.Vector(0,0,pos)) * T_S_F * velma.T_F_E
                    twist = PyKDL.diff(T_B_E, T_B_Ed, 1.0)
                    twist_v = (twist.rot.x()*twist.rot.x() + twist.rot.y()*twist.rot.y() + twist.rot.z()*twist.rot.z())
                    result = velma.isFramePossible(T_B_Ed)
                    if result[0] == False:
                        success = False
                        break
                    total_score += twist_v
                # prefer the pose with the smallest twist to the current pose
                if success and total_score < best_score:
                    best_score = total_score
                    best_angle_deg = angle_deg

            if best_score > 1000.0:
                print "it is impossible to reach the jar"
                rospy.sleep(1)
                exit(0)

            print "best_score: %s        best_angle_deg: %s"%(best_score, best_angle_deg)
            # set S frame destination for the best angle
            T_B_Sd = T_B_Sd * PyKDL.Frame(PyKDL.Rotation.RotZ(best_angle_deg/180.0*math.pi))

            T_B_Sd1 = T_B_Sd * PyKDL.Frame(PyKDL.Vector(0,0,-0.05))

            T_B_Sd2 = T_B_Sd * PyKDL.Frame(PyKDL.Vector(0,0,0.05))

            T_B_Wd = T_B_Sd1 * T_S_F * velma.T_F_E * velma.T_E_W

            velma.moveWrist2(T_B_Wd*velma.T_W_T)
            raw_input("Press Enter to move the robot...")
            if velma.checkStopCondition():
                exit(0)

            velma.moveWrist(T_B_Wd, 15, Wrench(Vector3(20,20,20), Vector3(4,4,4)))
            if velma.checkStopCondition(15):
                exit(0)

            velma.calibrateTactileSensors()

            # move down
            self.resetContacts()

            T_B_Wd = T_B_Sd2 * T_S_F * velma.T_F33_E * velma.T_E_W

            velma.moveWrist2(T_B_Wd*velma.T_W_T)
            raw_input("Press Enter to move the robot...")
            if velma.checkStopCondition():
                exit(0)

            velma.moveWrist(T_B_Wd, 6, Wrench(Vector3(20,20,20), Vector3(4,4,4)))
            # wait for contact
            contacts = velma.waitForFirstContact(50, 6.0, emergency_stop=True, f1=False, f2=False, f3=True, palm=False)
            if len(contacts) < 1:
                return
            for c in contacts:
                self.addContact(c)

            print "found contact point"
            for c in self.contacts:
                jar.addContactObservation(c)
            jar.drawContactObservations()

            # move up
            T_B_Wd = T_B_Sd1 * T_S_F * velma.T_F_E * velma.T_E_W

            velma.moveWrist(T_B_Wd, 3, Wrench(Vector3(20,20,20), Vector3(4,4,4)))
            if velma.checkStopCondition(3):
                exit(0)

            # update jar position
            print T_B_JC
            jar.processContactObservationsForTop()
            rospy.sleep(1.0)
            jar.drawContactObservations()
            T_B_JC = copy.deepcopy(jar.getJarCapFrame())
            print T_B_J

            raw_input("Press Enter to continue...")

        # now we want to touch the jar cap from 4 different sides using 2 fingers
        if True:
            # get the fresh pose of the jar
            T_B_JC = copy.deepcopy(jar.getJarCapFrame())

            # set gripper configuration for jar touching
            velma.move_hand_client("right", (0.0/180.0*numpy.pi, 0.0/180.0*numpy.pi, 0.0/180.0*numpy.pi, 90.0/180.0*numpy.pi) )
            if velma.checkStopCondition(3.0):
                exit(0)
            velma.updateTransformations()

            T_B_JCd = T_B_JC * PyKDL.Frame(PyKDL.Rotation.RotY(-180.0/180.0*math.pi)) * PyKDL.Frame(PyKDL.Vector(0,0,0.01))

            velma.updateTransformations()
            z5 = PyKDL.Frame(copy.deepcopy(velma.T_B_L5.M)) * PyKDL.Vector(0,0,1)
            T_B_E = velma.T_B_W * velma.T_W_E
            # find the best angle for touching the cap
            # iterate through angles
            best_score = 1000000.0
            best_angle_deg = 0.0
            for angle_deg in np.arange(0.0, 360.0, 10.0):
                total_score = 0.0
                print "angle_deg: %s"%(angle_deg)
                T_B_Ed = T_B_JCd * PyKDL.Frame(PyKDL.Rotation.RotZ(angle_deg/180.0*math.pi)) * T_JC_E_side_touch
                twist = PyKDL.diff(T_B_E, T_B_Ed, 1.0)
                twist_v = (twist.rot.x()*twist.rot.x() + twist.rot.y()*twist.rot.y() + twist.rot.z()*twist.rot.z())
                result1 = velma.isFramePossible(T_B_Ed)
                T_B_Ed = T_B_JCd * PyKDL.Frame(PyKDL.Rotation.RotZ((angle_deg+70.0)/180.0*math.pi)) * T_JC_E_side_touch
                twist = PyKDL.diff(T_B_E, T_B_Ed, 1.0)
                twist_v += (twist.rot.x()*twist.rot.x() + twist.rot.y()*twist.rot.y() + twist.rot.z()*twist.rot.z())
                result2 = velma.isFramePossible(T_B_Ed)

                # add penalty for singularity between L5 and L7
                T_B_W = T_B_Ed * velma.T_E_W
                z7 = PyKDL.Frame(T_B_W.M) * PyKDL.Vector(0,0,1)
                angle_5_7 = math.fabs(getAngle(z5, z7))
                if angle_5_7 < 20.0/180.0*math.pi:
                    penalty = 20.0 #20.0*(30.0/180.0*math.pi - angle_5_7)/(30.0/180.0*math.pi)
                else:
                    penalty = 0.0

                total_score = twist_v + penalty
                # prefer the pose with the smallest twist to the current pose
                if result1[0] and result2[0] and total_score < best_score:
                    best_score = total_score
                    best_angle_deg = angle_deg

            if best_score > 1000.0:
                print "it is impossible to reach the jar"
                rospy.sleep(1)
                exit(0)

            velma.calibrateTactileSensors()

            print "best_score: %s        best_angle_deg: %s"%(best_score, best_angle_deg)
            jar.resetContactObservations()

            T_B_Wd = T_B_JCd * PyKDL.Frame(PyKDL.Rotation.RotZ(best_angle_deg/180.0*math.pi)) * T_JC_E_side_touch * velma.T_E_W
            velma.moveWrist2(T_B_Wd*velma.T_W_T)
            raw_input("Press Enter to move the robot...")
            if velma.checkStopCondition():
                exit(0)

            velma.moveWrist(T_B_Wd, 8, Wrench(Vector3(20,20,20), Vector3(4,4,4)))
            if velma.checkStopCondition(8):
                exit(0)

            velma.move_hand_client("right", (100.0/180.0*numpy.pi, 100.0/180.0*numpy.pi, 0.0/180.0*numpy.pi, 90.0/180.0*numpy.pi), t=(1000, 1000, 1000, 1000) )
            if velma.checkStopCondition(3.0):
                exit(0)

            self.resetContacts()
            # get contacts for each finger
            for f in range(0, 2):
                contacts = velma.getContactPoints(200, f1=(f==0), f2=(f==1), f3=False, palm=False)
                mean_contact = PyKDL.Vector()
                for c in contacts:
                    mean_contact += c
                if len(contacts) > 0:
                    self.addContact((1.0/len(contacts))*mean_contact)

            for c in self.contacts:
                jar.addContactObservation(c)
            jar.drawContactObservations()

            velma.move_hand_client("right", (0.0/180.0*numpy.pi, 0.0/180.0*numpy.pi, 0.0/180.0*numpy.pi, 90.0/180.0*numpy.pi), t=(3000, 3000, 3000, 3000) )
            if velma.checkStopCondition(3.0):
                exit(0)








            T_B_Wd = T_B_JCd * PyKDL.Frame(PyKDL.Rotation.RotZ((best_angle_deg+70.0)/180.0*math.pi)) * T_JC_E_side_touch * velma.T_E_W
            velma.moveWrist2(T_B_Wd*velma.T_W_T)
            raw_input("Press Enter to move the robot...")
            if velma.checkStopCondition():
                exit(0)

            velma.moveWrist(T_B_Wd, 6, Wrench(Vector3(20,20,20), Vector3(4,4,4)))
            if velma.checkStopCondition(6):
                exit(0)

            velma.move_hand_client("right", (100.0/180.0*numpy.pi, 100.0/180.0*numpy.pi, 0.0/180.0*numpy.pi, 90.0/180.0*numpy.pi), t=(1000, 1000, 1000, 1000) )
            if velma.checkStopCondition(3.0):
                exit(0)

            self.resetContacts()
            # get contacts for each finger
            for f in range(0, 2):
                contacts = velma.getContactPoints(200, f1=(f==0), f2=(f==1), f3=False, palm=False)
                mean_contact = PyKDL.Vector()
                for c in contacts:
                    mean_contact += c
                if len(contacts) > 0:
                    self.addContact((1.0/len(contacts))*mean_contact)

            for c in self.contacts:
                jar.addContactObservation(c)
            jar.drawContactObservations()

            velma.move_hand_client("right", (0.0/180.0*numpy.pi, 0.0/180.0*numpy.pi, 0.0/180.0*numpy.pi, 90.0/180.0*numpy.pi), t=(3000, 3000, 3000, 3000) )
            if velma.checkStopCondition(3.0):
                exit(0)

            # now, we have very good pose of the jar
            jar.processContactObservations()

        # remove the cap
        if True:
            # get the fresh pose of the jar
            T_B_JC = copy.deepcopy(jar.getJarCapFrame())

            # set gripper configuration for jar decap
            velma.move_hand_client("right", (0.0/180.0*numpy.pi, 0.0/180.0*numpy.pi, 0.0/180.0*numpy.pi, spread_angle_cap_deg/180.0*numpy.pi) )
            if velma.checkStopCondition(3.0):
                exit(0)
            velma.updateTransformations()

            T_B_JCd = T_B_JC * PyKDL.Frame(PyKDL.Rotation.RotY(-180.0/180.0*math.pi)) * PyKDL.Frame(PyKDL.Vector(0,0,0.01))

            angle_cap_deg = 60.0

            velma.updateTransformations()
            T_B_E = velma.T_B_W * velma.T_W_E
            # find the best angle for rotating the cap
            # iterate through angles
            best_score = 1000000.0
            best_angle_deg = 0.0
            z5 = PyKDL.Frame(copy.deepcopy(velma.T_B_L5.M)) * PyKDL.Vector(0,0,1)
            for angle_deg in np.arange(0.0, 360.0, 10.0):
                success = True
                total_score = 0.0
                print "angle_deg: %s"%(angle_deg)
                # simulate the approach
                for beta_deg in np.arange(0.0, angle_cap_deg+0.1, 1.0):
                    # calculate the transform
                    T_B_Ed = T_B_JCd * PyKDL.Frame(PyKDL.Rotation.RotZ((angle_deg + beta_deg)/180.0*math.pi)) * T_JCdecap_E
                    twist = PyKDL.diff(T_B_E, T_B_Ed, 1.0)
                    twist_v = (twist.rot.x()*twist.rot.x() + twist.rot.y()*twist.rot.y() + twist.rot.z()*twist.rot.z())
                    result = velma.isFramePossible(T_B_Ed)
                    if result[0] == False:
                        success = False
                        break
                    # add penalty for singularity between L5 and L7
                    T_B_W = T_B_Ed * velma.T_E_W
                    z7 = PyKDL.Frame(T_B_W.M) * PyKDL.Vector(0,0,1)
                    angle_5_7 = math.fabs(getAngle(z5, z7))
                    if angle_5_7 < 30.0/180.0*math.pi:
                        penalty = 30.0
                    else:
                        penalty = 0.0
                    total_score += twist_v + penalty                    

                # prefer the pose with the smallest twist to the current pose
                if success and total_score < best_score:
                    best_score = total_score
                    best_angle_deg = angle_deg

            if best_score > 1000.0:
                print "it is impossible to reach the jar"
                rospy.sleep(1)
                exit(0)

            print "best_score: %s        best_angle_deg: %s"%(best_score, best_angle_deg)

            pos_z = 0.0

            # move to the start position
            T_B_Wd = T_B_JCd * PyKDL.Frame(PyKDL.Vector(0,0,-pos_z)) * PyKDL.Frame(PyKDL.Rotation.RotZ((best_angle_deg+angle_cap_deg)/180.0*math.pi)) * T_JCdecap_E * velma.T_E_W
            velma.moveWrist2(T_B_Wd*velma.T_W_T)
            raw_input("Press Enter to move the robot...")
            if velma.checkStopCondition():
                exit(0)
            velma.moveWrist(T_B_Wd, 10, Wrench(Vector3(20,20,20), Vector3(4,4,4)))
            if velma.checkStopCondition(10):
                exit(0)

            opened = False
            while True:
                # correct gripper configuration for jar cap
                velma.move_hand_client("right", (cap_hangle_q[0] - 20.0/180.0*numpy.pi, cap_hangle_q[1] - 20.0/180.0*numpy.pi, cap_hangle_q[2] - 20.0/180.0*numpy.pi, spread_angle_cap_deg/180.0*numpy.pi) )
                if velma.checkStopCondition(3.0):
                    exit(0)

                # move to the start position
                T_B_Wd = T_B_JCd * PyKDL.Frame(PyKDL.Vector(0,0,-pos_z)) * PyKDL.Frame(PyKDL.Rotation.RotZ((best_angle_deg+angle_cap_deg)/180.0*math.pi)) * T_JCdecap_E * velma.T_E_W
                velma.moveWrist2(T_B_Wd*velma.T_W_T)
                raw_input("Press Enter to move the robot...")
                if velma.checkStopCondition():
                    exit(0)
                velma.moveWrist(T_B_Wd, 3.0, Wrench(Vector3(20,20,20), Vector3(4,4,4)))
                velma.moveImpedance(k_jar_cap_gripping, 2.0)
                if velma.checkStopCondition(3.0):
                    exit(0)

                raw_input("Press Enter to move the robot...")
                if velma.checkStopCondition():
                    exit(0)

                # close the fingers on the cap
                velma.move_hand_client("right", (cap_hangle_q[0], cap_hangle_q[1], cap_hangle_q[2], spread_angle_cap_deg/180.0*numpy.pi), t=(3000, 3000, 3000, 3000) )
                if velma.checkStopCondition(3.0):
                    exit(0)

                # close the fingers stronger on the cap
                velma.move_hand_client("right", (cap_hangle_q[0] + 10.0/180.0*numpy.pi, cap_hangle_q[1] + 10.0/180.0*numpy.pi, cap_hangle_q[2] + 10.0/180.0*numpy.pi, spread_angle_cap_deg/180.0*numpy.pi), t=(1000, 1000, 1000, 1000) )
                if velma.checkStopCondition(1.5):
                    exit(0)

                velma.moveImpedance(k_jar_cap_rotating, 2.0)
                if velma.checkStopCondition(2.0):
                    exit(0)

                # rotate the cap
                for beta_deg in np.arange(angle_cap_deg, -0.1, -2.0):
                    print "beta_deg: %s"%(beta_deg)
                    T_B_Wd = T_B_JCd * PyKDL.Frame(PyKDL.Vector(0,0,-pos_z)) * PyKDL.Frame(PyKDL.Rotation.RotZ((best_angle_deg + beta_deg)/180.0*math.pi)) * T_JCdecap_E * velma.T_E_W
                    velma.moveWrist(T_B_Wd, 0.5, Wrench(Vector3(20,20,20), Vector3(4,4,4)))
                    if velma.checkStopCondition(0.5):
                        exit(0)

                # pull the cap
                T_B_Wd = T_B_JCd * PyKDL.Frame(PyKDL.Vector(0,0,-pos_z)) * PyKDL.Frame(PyKDL.Vector(0,0,-0.07)) * PyKDL.Frame(PyKDL.Rotation.RotZ((best_angle_deg + 0.0)/180.0*math.pi)) * T_JCdecap_E * velma.T_E_W
                velma.moveWrist2(T_B_Wd * velma.T_W_T)
                raw_input("Press Enter to move the gripper...")
                if velma.checkStopCondition():
                    exit(0)
                self.resetContacts()
                velma.moveWrist(T_B_Wd, 6.0, Wrench(Vector3(20,20,20), Vector3(4,4,4)))

                end_t = rospy.Time.now() + rospy.Duration(6.0)
                lost_contact = False
                no_contact = 0
                while rospy.Time.now() < end_t:
                    contacts = velma.getContactPoints(200, f1=True, f2=True, f3=True, palm=False)
                    if len(contacts) < 1:
                         no_contact += 1
                    else:
                         no_contact = 0
                    if no_contact > 5:
                         lost_contact = True
                    for c in contacts:
                        self.addContact(c)
                    if velma.checkStopCondition(0.05):
                        exit(0)

                if len(self.contacts) < 1:
                    print "no contact with the jar"
                    break

                if not lost_contact:
                    print "we are still holding the cap -> the jar is opened!"
                    opened = True
                    break
                max_z = 0.0
                for c in self.contacts:
                    c_in_J = T_B_JC.Inverse() * c
                    if c_in_J.z() > max_z:
                        max_z = c_in_J.z()

                pos_z = max_z - 0.015
                print "max_z: %s"%(max_z)
                print "pos_z: %s"%(pos_z)
                raw_input("Press Enter to continue...")
                if velma.checkStopCondition():
                    exit(0)

        # for test
#        opened = True

        if not opened:
            exit(0)

        # get the angle of L6 in L5 anlong L5.y axis
        velma.updateTransformations()
        T_L6_L7 = velma.T_B_L6.Inverse() * velma.T_B_L7
        T_L5_L6 = velma.T_B_L5.Inverse() * velma.T_B_L6
        z6in5 = PyKDL.Frame(T_L5_L6.M) * PyKDL.Vector(0,0,1)
        angle6in5 = math.atan2(z6in5.x(), z6in5.z())

        angle6in5_dest = -90.0/180.0*math.pi
        omega = 10.0/180.0*math.pi
        time_d = 0.01
        if angle6in5_dest < angle6in5:
           omega = -omega
        stop = False
        angle = angle6in5
        times = []
        time = 0.5
        tab_T_B_Wd = []
        while not stop:
            angle += omega * time_d
            time += time_d
            if angle6in5_dest > angle6in5 and angle > angle6in5_dest:
                angle = angle6in5_dest
                stop = True
            if angle6in5_dest < angle6in5 and angle < angle6in5_dest:
                angle = angle6in5_dest
                stop = True
            T_L5_L6d = PyKDL.Frame(PyKDL.Rotation.RotY(angle),T_L5_L6.p)
            T_B_Wd = velma.T_B_L5 * T_L5_L6d * T_L6_L7
            tab_T_B_Wd.append(T_B_Wd)
            times.append(time)

        velma.moveWristTraj( tab_T_B_Wd, times, Wrench(Vector3(20,20,20), Vector3(4,4,4)) )
        if velma.checkStopCondition(time):
            exit(0)

        exit(0)

if __name__ == '__main__':

    rospy.init_node('jar_opener')

    global br
    pub_marker = MarkerPublisher()
    task = JarOpener(pub_marker)
    rospy.sleep(1)
    br = tf.TransformBroadcaster()

    task.spin()
    



