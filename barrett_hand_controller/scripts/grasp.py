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
import random
from openravepy import *
from optparse import OptionParser
from openravepy.misc import OpenRAVEGlobalArguments
import velmautils
import openraveinstance
import itertools
import dijkstra

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

class GraspableObject:
    def __init__(self, name, obj_type, size):
        self.name = name
        self.obj_type = obj_type
        self.size = size
        self.com = PyKDL.Vector()
        self.markers = []
        self.T_Br_Co = PyKDL.Frame()
        self.pose_update_time = rospy.Time.now()

    def addMarker(self, marker_id, T_Co_M):
        self.markers.append( (marker_id, T_Co_M) )

    def isBox(self):
        if self.obj_type == "box":
            return True
        return False

    def updatePose(self, T_Br_Co):
        self.T_Br_Co = T_Br_Co
        self.pose_update_time = rospy.Time.now()

class Grip:
    def __init__(self, grasped_object):
        self.grasped_object = grasped_object
        self.contacts = []
        self.successful = False

    def addContact(self, T_O_Co):
        self.contacts.append(copy.deepcopy(T_O_Co))

    def success(self):
        self.successful = True

    def serializePrint(self):
        print "grips_db.append( Grip(obj_grasp) )"
        for c in self.contacts:
            q = c.M.GetQuaternion()
            print "grips_db[-1].addContact( PyKDL.Frame(PyKDL.Rotation.Quaternion(%s,%s,%s,%s),PyKDL.Vector(%s,%s,%s)) )"%(q[0], q[1], q[2], q[3], c.p.x(), c.p.y(), c.p.z())
        if self.successful:
            print "grips_db[-1].success()"

def gripDist(a, b):
    def estTransform(l1, l2):
        pos1 = []
        n1 = []
        for f in l1:
            pos1.append( f * PyKDL.Vector() )
            n1.append( PyKDL.Frame(f.M) * PyKDL.Vector(0,0,1) )
        def calc_R(xa, ya, za):
            ret = []
            """ calculate the minimum distance of each contact point from jar surface pt """
            t = PyKDL.Frame(PyKDL.Rotation.RotX(xa)) * PyKDL.Frame(PyKDL.Rotation.RotY(ya)) * PyKDL.Frame(PyKDL.Rotation.RotZ(za))
            index1 = 0
            for f in l2:
                dest_f = t * f
                pos2 = dest_f * PyKDL.Vector()
                n2 = PyKDL.Frame(dest_f.M) * PyKDL.Vector(0,0,1)
                ret.append((pos1[index1]-pos2).Norm()*5.0 + math.fabs(velmautils.getAngle(n1[index1],n2))/math.pi)
                index1 += 1
            return numpy.array(ret)
        def f_2(c):
            """ calculate the algebraic distance between each contact point and jar surface pt """
            Di = calc_R(*c)
            return Di
        angles_estimate = 0.0, 0.0, 0.0
        angles_2, ier = optimize.leastsq(f_2, angles_estimate, maxfev = 1000)
        t = PyKDL.Frame(PyKDL.Rotation.RotX(angles_2[0])) * PyKDL.Frame(PyKDL.Rotation.RotY(angles_2[1])) * PyKDL.Frame(PyKDL.Rotation.RotZ(angles_2[2]))
        index1 = 0
        score = 0.0
        for f in l2:
            dest_f = t * f
            pos2 = dest_f * PyKDL.Vector()
            n2 = PyKDL.Frame(dest_f.M) * PyKDL.Vector(0,0,1)
            score += ((pos1[index1]-pos2).Norm()*5.0 + math.fabs(velmautils.getAngle(n1[index1],n2))/math.pi)
            index1 += 1
        return score, angles_2

    fr_a = []
    for fr in a.contacts:
        fr_a.append( PyKDL.Frame(-a.grasped_object.com) * fr )

    fr_b = []
    for fr in b.contacts:
        fr_b.append( PyKDL.Frame(-b.grasped_object.com) * fr )

    if len(fr_a) > len(fr_b):
        fr_0 = fr_a
        fr_1 = fr_b
    else:
        fr_0 = fr_b
        fr_1 = fr_a

    min_score = 10000.0
    min_angles = None
#    print "scores:"
    # estimate for each permutation of the smaller set
    for it in itertools.permutations(fr_1):
        score, angles = estTransform(fr_0, it)
        if score < min_score:
            min_score = score
            min_angles = angles
#        print score
    return min_score, min_angles


class GraspingTask:
    """
Class for grasp learning.
"""

    def __init__(self, pub_marker=None):
        self.pub_marker = pub_marker
        self.listener = tf.TransformListener();

    def getMarkerPose(self, marker_id, wait = True, timeBack = None):
        try:
            marker_name = 'ar_marker_'+str(int(marker_id))
            if wait:
                self.listener.waitForTransform('torso_base', marker_name, rospy.Time.now(), rospy.Duration(4.0))
            if timeBack != None:
                time = rospy.Time.now() - rospy.Duration(timeBack)
            else:
                time = rospy.Time(0)
            jar_marker = self.listener.lookupTransform('torso_base', marker_name, time)
        except:
            return None
        return pm.fromTf(jar_marker)

    def poseUpdaterThread(self, args, *args2):
        index = 0
        while not rospy.is_shutdown():
            rospy.sleep(0.1)
            if self.allow_update_objects_pose == None or not self.allow_update_objects_pose:
                continue
#            visible_markers = []
            for obj in self.objects:
                for marker in obj.markers:
                    T_Br_M = self.getMarkerPose(marker[0], wait = False, timeBack = 0.3)
                    if T_Br_M != None:
#                        visible_markers.append(marker[0])
                        T_Co_M = marker[1]
                        T_Br_Co = T_Br_M * T_Co_M.Inverse()
                        obj.updatePose(T_Br_Co)
                        self.openrave.updatePose(obj.name, T_Br_Co)
                        break
#            print "%s   visible_markers: %s"%(index, visible_markers)

            index += 1
            if index >= 100:
                index = 0

    def allowUpdateObjects(self):
        self.allow_update_objects_pose = True

    def disallowUpdateObjects(self):
        self.allow_update_objects_pose = False

    def spin(self):
        m_id = 0

        # create the robot interface
        velma = Velma()

        self.openrave = openraveinstance.OpenraveInstance(velma, PyKDL.Frame(PyKDL.Vector(0,0,0.1)))
        self.openrave.startNewThread()

        while not rospy.is_shutdown():
            if self.openrave.rolling:
                break
            rospy.sleep(0.5)

        obj_table = GraspableObject("table", "box", [0.60,0.85,0.07])
        obj_table.addMarker( 6, PyKDL.Frame(PyKDL.Vector(0, -0.225, 0.035)) )

        obj_box = GraspableObject("box", "box", [0.22,0.24,0.135])
        obj_box.addMarker( 7, PyKDL.Frame(PyKDL.Vector(-0.07, 0.085, 0.065)) )

#        obj_grasp = GraspableObject("object", "box", [0.060,0.354,0.060])
        obj_grasp = GraspableObject("object", "box", [0.354, 0.060, 0.060])
        obj_grasp_frames = [
        [18, PyKDL.Frame(PyKDL.Rotation.Quaternion(0.0,0.0,0.0,1.0),PyKDL.Vector(-0.0,-0.0,-0.0))],
        [19, PyKDL.Frame(PyKDL.Rotation.Quaternion(-0.00785118489648,-0.00136981350282,-0.000184602454162,0.999968223709),PyKDL.Vector(0.14748831582,-0.00390004064458,0.00494675382036))],
        [20, PyKDL.Frame(PyKDL.Rotation.Quaternion(-0.0108391070454,-0.00679278400361,-0.0154191552083,0.999799290606),PyKDL.Vector(0.289969171073,-0.00729932931459,0.00759828464719))],
        [21, PyKDL.Frame(PyKDL.Rotation.Quaternion(0.707914450157,0.00553703354292,-0.0049088621984,0.706259425134),PyKDL.Vector(-0.00333471065688,-0.0256403932819,-0.0358967610179))],
        [22, PyKDL.Frame(PyKDL.Rotation.Quaternion(0.711996124932,0.000529252451241,-0.00578615630039,0.702159353971),PyKDL.Vector(0.147443644368,-0.03209918445,-0.028549100504))],
        [23, PyKDL.Frame(PyKDL.Rotation.Quaternion(0.714618336612,-0.00917868744082,0.000177822438207,0.699454325209),PyKDL.Vector(0.29031370529,-0.0348959795876,-0.0263138015496))],
        [24, PyKDL.Frame(PyKDL.Rotation.Quaternion(-0.999814315554,-0.00730751409695,0.00318617054665,0.0175437444253),PyKDL.Vector(-0.00774666114837,0.0127324931914,-0.0605032370936))],
        [25, PyKDL.Frame(PyKDL.Rotation.Quaternion(-0.999769709131,-0.00683690807754,0.00565692317327,0.0195393093955),PyKDL.Vector(0.143402769587,0.00560941008048,-0.0682080677974))],
        [26, PyKDL.Frame(PyKDL.Rotation.Quaternion(-0.999702001968,0.00436508873022,0.00893993421014,0.0222919455689),PyKDL.Vector(0.2867315755,0.0037977729025,-0.0723254241133))],
        [27, PyKDL.Frame(PyKDL.Rotation.Quaternion(-0.718926115108,0.0025958563067,0.000863904789675,0.695081114845),PyKDL.Vector(0.00685389266037,0.041611313921,-0.0242848250842))],
        [28, PyKDL.Frame(PyKDL.Rotation.Quaternion(-0.723920159064,-0.00406580031329,-0.00237155614562,0.689867703469),PyKDL.Vector(0.152973875805,0.0480443334089,-0.0203619760073))],
        [29, PyKDL.Frame(PyKDL.Rotation.Quaternion(-0.730592084981,-0.0115053876764,-0.00159217841913,0.682715384612),PyKDL.Vector(0.296627722109,0.0526564873934,-0.0157362559562))],
        [30, PyKDL.Frame(PyKDL.Rotation.Quaternion(-0.0107101025933,-0.707578018883,-0.00676540180519,0.706521670039),PyKDL.Vector(-0.0316984701649,0.00141765295049,-0.0308603633287))],
        [31, PyKDL.Frame(PyKDL.Rotation.Quaternion(0.00385143207656,0.706841586598,0.00284731518612,0.707355660699),PyKDL.Vector(0.319944660728,-0.00029327409029,-0.0292236368986))],
        ]
        T_M18_M19 = obj_grasp_frames[1][1]
        T_M19_Co = PyKDL.Frame(PyKDL.Vector(0,0,-0.03))
        T_M18_Co = T_M18_M19 * T_M19_Co
        T_Co_M18 = T_M18_Co.Inverse()
        for marker in obj_grasp_frames:
            T_M18_Mi = marker[1]
            obj_grasp.addMarker(marker[0], T_Co_M18 * T_M18_Mi)

        self.objects = [obj_table, obj_box, obj_grasp]

        for obj in self.objects:
            if obj.isBox():
                self.openrave.addBox(obj.name, obj.size[0], obj.size[1], obj.size[2])

        if False:
            index = 18
            for fr in frames:
                print index
                m_id = self.pub_marker.publishFrameMarker(fr, m_id)
                raw_input("Press Enter to continue...")
                rospy.sleep(0.1)
                index += 1
            rospy.sleep(2.0)

            exit(0)

        # unit test for distance measurement between grips
        if False:
            # distance between identical grips
            print "distance between identical grips"
            grip1 = Grip(obj_grasp)
            grip1.addContact(PyKDL.Frame(PyKDL.Rotation.RotX(90.0/180.0*math.pi), PyKDL.Vector(-0.1,-0.03,0)))
            grip1.addContact(PyKDL.Frame(PyKDL.Rotation.RotX(90.0/180.0*math.pi), PyKDL.Vector(-0.05,-0.03,0)))
            grip1.addContact(PyKDL.Frame(PyKDL.Rotation.RotX(-90.0/180.0*math.pi), PyKDL.Vector(-0.075,0.03,0)))
            grip2 = copy.deepcopy(grip1)
            print gripDist(grip1, grip2)

            # distance between identical grips rotated in com
            print "distance between identical grips rotated in com"
            grip2 = copy.deepcopy(grip1)
            for i in range(0, len(grip2.contacts)):
                grip2.contacts[i] = PyKDL.Frame(PyKDL.Rotation.RotX(90.0/180.0*math.pi)) * grip2.contacts[i]
            print gripDist(grip1, grip2)

            # distance between identical grips rotated in com in 2 directions
            print "distance between identical grips rotated in com in 2 directions"
            grip2 = copy.deepcopy(grip1)
            for i in range(0, len(grip2.contacts)):
                grip2.contacts[i] = PyKDL.Frame(PyKDL.Rotation.RotX(90.0/180.0*math.pi)) * PyKDL.Frame(PyKDL.Rotation.RotZ(20.0/180.0*math.pi)) * grip2.contacts[i]
            print gripDist(grip1, grip2)

            # distance between identical grips rotated in com in 2 directions, one grip has additional contact
            print "distance between identical grips rotated in com in 2 directions, one grip has additional contact"
            grip2 = copy.deepcopy(grip1)
            for i in range(0, len(grip2.contacts)):
                grip2.contacts[i] = PyKDL.Frame(PyKDL.Rotation.RotX(90.0/180.0*math.pi)) * PyKDL.Frame(PyKDL.Rotation.RotZ(20.0/180.0*math.pi)) * grip2.contacts[i]
            grip2.addContact(PyKDL.Frame(PyKDL.Rotation.RotX(-90.0/180.0*math.pi), PyKDL.Vector(-0.01,0.03,0)))
            print gripDist(grip1, grip2)

            # distance between identical grips rotated in com in 2 directions, one grip has a bit diffrent one contact pos
            print "distance between identical grips rotated in com in 2 directions, one grip has a bit diffrent one contact pos"
            grip2 = copy.deepcopy(grip1)
            grip2.contacts[0] = PyKDL.Frame(PyKDL.Rotation.RotX(90.0/180.0*math.pi), PyKDL.Vector(-0.11,-0.03,0))
            print gripDist(grip1, grip2)

            # distance between identical grips rotated in com in 2 directions, one grip has a bit diffrent one contact rot
            print "distance between identical grips rotated in com in 2 directions, one grip has a bit diffrent one contact rot"
            grip2 = copy.deepcopy(grip1)
            grip2.contacts[0] = PyKDL.Frame(PyKDL.Rotation.RotX(70.0/180.0*math.pi), PyKDL.Vector(-0.1,-0.03,0))
            print gripDist(grip1, grip2)

            # distance between identical grips rotated in conter of the object, with different com
            print "distance between identical grips rotated in conter of the object, with different com"
            obj_grasp.com = PyKDL.Vector(0,-0.01,0)
            grip1.grasped_object = obj_grasp
            grip2 = copy.deepcopy(grip1)
            for i in range(0, len(grip2.contacts)):
                grip2.contacts[i] = PyKDL.Frame(PyKDL.Rotation.RotX(-90.0/180.0*math.pi)) * grip2.contacts[i]
            print gripDist(grip1, grip2)
            obj_grasp.com = PyKDL.Vector(0,0,0)

            exit(0)

        # unit test for surface sampling
        if False:
            vertices, indices = self.openrave.getMesh("object")
            print vertices
            print indices
            points = velmautils.sampleMesh(vertices, indices, 0.002, [PyKDL.Vector(0.00,0,0.00)], 0.04)
            print len(points)
            m_id = 0
            m_id = self.pub_marker.publishMultiPointsMarker(points, m_id, r=1, g=0, b=0, namespace='default', frame_id='torso_base', m_type=Marker.CUBE, scale=Vector3(0.001, 0.001, 0.001))
            raw_input("Press Enter to continue...")

            rospy.sleep(5.0)

            pt_list = []
            for i in range(0, 20):
                pt_list.append(PyKDL.Vector((1.0*i/20.0)*0.1-0.05, 0, 0))
            points = velmautils.sampleMesh(vertices, indices, 0.002, pt_list, 0.01)
            print len(points)
            m_id = 0
            m_id = self.pub_marker.publishMultiPointsMarker(points, m_id, r=1, g=0, b=0, namespace='default', frame_id='torso_base', m_type=Marker.CUBE, scale=Vector3(0.001, 0.001, 0.001))
            rospy.sleep(1.0)
            fr = velmautils.estPlane(points)
            m_id = self.pub_marker.publishFrameMarker(fr, m_id)
            rospy.sleep(1.0)
            exit(0)

        # unit test for hand kinematics
        if False:
            m_id = 0
            velma.updateTransformations()
            finger = 0
            center = PyKDL.Vector(0.05,-0.01,0)
            T_E_Fi3 = [velma.T_E_F13, velma.T_E_F23, velma.T_E_F33]
            T_Fi3_E = [velma.T_F13_E, velma.T_F23_E, velma.T_F33_E]
            centers = [velma.T_B_W * velma.T_W_E * velma.T_E_F13 * center, velma.T_B_W * velma.T_W_E * velma.T_E_F23 * center, velma.T_B_W * velma.T_W_E * velma.T_E_F33 * center]
            for c in centers:
                if c != None:
                    c_Fi3 = T_Fi3_E[finger] * velma.T_E_W * velma.T_B_W.Inverse() * c
                    pt_list = []
                    for angle in np.linspace(velma.q_rf[finger*3 + 1]-0.0/180.0*math.pi, velma.q_rf[finger*3 + 1]+10.0/180.0*math.pi, 20):
                        T_E_F = velma.get_T_E_Fd(finger, angle, 0)
                        cn_B = velma.T_B_W * velma.T_W_E * T_E_F * c_Fi3
                        pt_list.append(cn_B)
                    m_id = self.pub_marker.publishMultiPointsMarker(pt_list, m_id, r=1, g=1, b=0, namespace='default', frame_id='torso_base', m_type=Marker.CUBE, scale=Vector3(0.004, 0.004, 0.004))#, T=T_Br_O)
                finger += 1
            exit(0)

        self.allowUpdateObjects()
        # start thread for updating objects' positions in openrave
        thread.start_new_thread(self.poseUpdaterThread, (None,1))

        velma.updateTransformations()

        k_pregrasp = Wrench(Vector3(1000.0, 1000.0, 1000.0), Vector3(300.0, 300.0, 300.0))
        k_grasp = Wrench(Vector3(500.0, 500.0, 500.0), Vector3(150.0, 150.0, 150.0))

        if True:
            # reset the gripper
            velma.reset_fingers()
            velma.calibrate_tactile_sensors()
            velma.set_median_filter(8)

            # start with very low stiffness
            print "setting stiffness to very low value"
            velma.moveImpedance(velma.k_error, 0.5)
            if velma.checkStopCondition(0.5):
                exit(0)

            raw_input("Press Enter to continue...")
            if velma.checkStopCondition():
                exit(0)

            velma.updateTransformations()
            velma.updateAndMoveTool( velma.T_W_E, 1.0 )
            if velma.checkStopCondition(1.0):
                exit(0)

            raw_input("Press Enter to continue...")
            print "setting stiffness to bigger value"
            velma.moveImpedance(k_pregrasp, 3.0)
            if velma.checkStopCondition(3.0):
                exit(0)

        velma.updateTransformations()
        velma_init_T_B_W = copy.deepcopy(velma.T_B_W)
        grips_db = []
        while True:
            self.disallowUpdateObjects()

            grasps,indices = self.openrave.generateGrasps("object")

            min_cost = 10000.0
            min_i = 0
            for i in range(0, len(grasps)):
                T_Br_E = self.openrave.getGraspTransform(grasps[i], collisionfree=True)
                velma.updateTransformations()
                traj_T_B_Ed = [T_Br_E]
                cost = velma.getTrajCost(traj_T_B_Ed, False, False)
                print "%s   cost: %s"%(i,cost)
                if cost < min_cost:
                    min_cost = cost
                    min_i = i

            if min_cost > 1000.0:
                print "could not reach the destination point"
                break

            print "found grasp"
            grasp = grasps[min_i]

            T_Br_E = self.openrave.getGraspTransform(grasp, collisionfree=True)
            self.openrave.showGrasp(grasp)

            T_B_Wd = T_Br_E * velma.T_E_W
            duration = velma.getMovementTime(T_B_Wd, max_v_l=0.1, max_v_r=0.2)
            velma.moveWrist2(T_B_Wd*velma.T_W_T)
            self.openrave.showTrajectory(T_Br_E, 3.0, grasp)

            final_config = self.openrave.getFinalConfig(grasp)
            print "final_config:"
            print final_config
            print "standoff: %s"%(self.openrave.getGraspStandoff(grasp))

            raw_input("Press Enter to move the robot in " + str(duration) + " s...")
            if velma.checkStopCondition():
                break
            velma.moveWrist(T_B_Wd, duration, Wrench(Vector3(20,20,20), Vector3(4,4,4)), abort_on_q5_singularity=True, abort_on_q5_q6_self_collision=True)
            if velma.checkStopCondition(duration):
                break

            raw_input("Press Enter to close fingers for pre-grasp...")
            # close the fingers for pre-grasp
            ad = 10.0/180.0*math.pi
            velma.move_hand_client([final_config[0]-ad, final_config[1]-ad, final_config[2]-ad, final_config[3]], v=(1.2, 1.2, 1.2, 1.2), t=(3000.0, 3000.0, 3000.0, 3000.0))

            print "setting stiffness to lower value"
            velma.moveImpedance(k_grasp, 3.0)
            if velma.checkStopCondition(3.0):
                break

            raw_input("Press Enter to close fingers for grasp...")

            # close the fingers for grasp
            velma.move_hand_client((120.0/180.0*math.pi,120.0/180.0*math.pi,120.0/180.0*math.pi,0), v=(1.2, 1.2, 1.2, 1.2), t=(1500.0, 1500.0, 1500.0, 1500.0))
            m_id = 0
            if True:
                if velma.checkStopCondition(3.0):
                    break
            else:
                time_end = rospy.Time.now() + rospy.Duration(3.0)
                all_contacts = []
                all_forces = []
                while rospy.Time.now() < time_end:
                    contacts = [[],[],[]]
                    forces = [[],[],[]]
                    contacts[0], forces[0] = velma.getContactPoints(100, f1=True, f2=False, f3=False, palm=False)
                    contacts[1], forces[1] = velma.getContactPoints(100, f1=False, f2=True, f3=False, palm=False)
                    contacts[2], forces[2] = velma.getContactPoints(100, f1=False, f2=False, f3=True, palm=False)
                    if len(contacts) > 0:
                        all_contacts.append(contacts)
                        all_forces.append(forces)
                    rospy.sleep(0.01)
                    if velma.checkStopCondition():
                        break
                for c in all_contacts:
                    m_id = self.pub_marker.publishMultiPointsMarker(c[0], m_id, r=1, g=0, b=0, namespace='default', frame_id='torso_base', m_type=Marker.CUBE, scale=Vector3(0.001, 0.001, 0.001))
                    rospy.sleep(0.01)
                    m_id = self.pub_marker.publishMultiPointsMarker(c[1], m_id, r=0, g=1, b=0, namespace='default', frame_id='torso_base', m_type=Marker.CUBE, scale=Vector3(0.001, 0.001, 0.001))
                    rospy.sleep(0.01)
                    m_id = self.pub_marker.publishMultiPointsMarker(c[2], m_id, r=0, g=0, b=1, namespace='default', frame_id='torso_base', m_type=Marker.CUBE, scale=Vector3(0.001, 0.001, 0.001))
                    rospy.sleep(0.01)

            # get contact points and forces for each finger
            velma.updateTransformations()
            contacts = [[],[],[]]
            forces = [[],[],[]]
            contacts[0], forces[0] = velma.getContactPoints(100, f1=True, f2=False, f3=False, palm=False)
            contacts[1], forces[1] = velma.getContactPoints(100, f1=False, f2=True, f3=False, palm=False)
            contacts[2], forces[2] = velma.getContactPoints(100, f1=False, f2=False, f3=True, palm=False)

            m_id = self.pub_marker.publishMultiPointsMarker(contacts[0], m_id, r=1, g=0, b=0, namespace='default', frame_id='torso_base', m_type=Marker.CUBE, scale=Vector3(0.001, 0.001, 0.001))
            rospy.sleep(0.01)
            m_id = self.pub_marker.publishMultiPointsMarker(contacts[1], m_id, r=0, g=1, b=0, namespace='default', frame_id='torso_base', m_type=Marker.CUBE, scale=Vector3(0.001, 0.001, 0.001))
            rospy.sleep(0.01)
            m_id = self.pub_marker.publishMultiPointsMarker(contacts[2], m_id, r=0, g=0, b=1, namespace='default', frame_id='torso_base', m_type=Marker.CUBE, scale=Vector3(0.001, 0.001, 0.001))
            rospy.sleep(0.01)

            # calculate force-weighted center of contacts for each finger
            centers = []
            number_of_fingers_in_contact = 0
            forces_sum = []
            for finger in range(0, len(contacts)):
                center = PyKDL.Vector()
                force_sum = 0.0
                for i in range(0, len(contacts[finger])):
                    center += contacts[finger][i] * forces[finger][i]
                    force_sum += forces[finger][i]
                forces_sum.append(force_sum)
                if force_sum > 0.0:
                    center *= (1.0/force_sum)
                    centers.append(center)
                    number_of_fingers_in_contact += 1
                else:
                    centers.append(None)

            print "fingers in contact: %s"%(number_of_fingers_in_contact)
            if number_of_fingers_in_contact < 2:
                print "could not grasp the object with more than 1 finger"
                break

            grip = Grip(obj_grasp)

            for c in centers:
                if c != None:
                    m_id = self.pub_marker.publishSinglePointMarker(c, m_id, r=1, g=1, b=1, namespace='default', frame_id='torso_base', m_type=Marker.CUBE, scale=Vector3(0.001, 0.001, 0.001))

            T_Br_O = obj_grasp.T_Br_Co

            T_E_Co_before = velma.T_E_W * velma.T_B_W.Inverse() * T_Br_O

            T_O_Br = T_Br_O.Inverse()
            vertices, indices = self.openrave.getMesh("object")
            finger = 0
            T_E_Fi3 = [velma.T_E_F13, velma.T_E_F23, velma.T_E_F33]
            T_Fi3_E = [velma.T_F13_E, velma.T_F23_E, velma.T_F33_E]
            actual_angles = [velma.q_rf[1], velma.q_rf[4], velma.q_rf[6]]
            for c in centers:
                if c != None:
                    c_Fi3 = T_Fi3_E[finger] * velma.T_E_W * velma.T_B_W.Inverse() * c
                    pt_list = []
                    for angle in np.linspace(actual_angles[finger]-10.0/180.0*math.pi, actual_angles[finger]+10.0/180.0*math.pi, 20):
                        T_E_F = velma.get_T_E_Fd(finger, angle, 0)
                        cn_B = velma.T_B_W * velma.T_W_E * T_E_F * c_Fi3
                        cn_O = T_O_Br * cn_B
                        pt_list.append(cn_O)
                    m_id = self.pub_marker.publishMultiPointsMarker(pt_list, m_id, r=1, g=1, b=0, namespace='default', frame_id='torso_base', m_type=Marker.CUBE, scale=Vector3(0.004, 0.004, 0.004), T=T_Br_O)
                    points = velmautils.sampleMesh(vertices, indices, 0.002, pt_list, 0.01)
                    print len(points)
                    m_id = self.pub_marker.publishMultiPointsMarker(points, m_id, r=1, g=0, b=0, namespace='default', frame_id='torso_base', m_type=Marker.CUBE, scale=Vector3(0.004, 0.004, 0.004), T=T_Br_O)
                    rospy.sleep(1.0)
                    # get the contact surface normal
                    fr = velmautils.estPlane(points)
                    # set the proper direction of the contact surface normal (fr.z axis)
                    if PyKDL.dot( T_Br_O * fr * PyKDL.Vector(0,0,1), velma.T_B_W * velma.T_W_E * T_E_Fi3[finger] * PyKDL.Vector(1,-1,0) ) > 0:
                        fr = fr * PyKDL.Frame(PyKDL.Rotation.RotX(180.0/180.0*math.pi))
                    # add the contact to the grip description
                    grip.addContact(fr)
                    m_id = self.pub_marker.publishFrameMarker(T_Br_O*fr, m_id)
                    rospy.sleep(1.0)
                finger += 1

            self.allowUpdateObjects()

            # lift the object up
            velma.updateTransformations()

            T_B_Wd = PyKDL.Frame(PyKDL.Vector(0,0,0.05)) * velma.T_B_W
            duration = velma.getMovementTime(T_B_Wd, max_v_l=0.1, max_v_r=0.2)
            velma.moveWrist2(T_B_Wd*velma.T_W_T)
            raw_input("Press Enter to lift the object up in " + str(duration) + " s...")
            if velma.checkStopCondition():
                break
            velma.moveWrist(T_B_Wd, duration, Wrench(Vector3(20,20,20), Vector3(4,4,4)), abort_on_q5_singularity=True, abort_on_q5_q6_self_collision=True)
            if velma.checkStopCondition(duration):
                break

            if velma.checkStopCondition(2.0):
                break

            contacts, forces = velma.getContactPoints(200, f1=True, f2=True, f3=True, palm=False)
            if len(contacts) > 0:
                print "Still holding the object. Contacts: %s"%(len(contacts))
                holding = True
            else:
                holding = False

            # try to get fresh object pose
            dur = rospy.Time.now() - obj_grasp.pose_update_time
            if dur.to_sec() < 1.0:
                fresh_pose = True
            else:
                fresh_pose = False

            velma.updateTransformations()
            if fresh_pose:
                print "we can still see the object!"
                T_E_Co_after = velma.T_E_W * velma.T_B_W.Inverse() * obj_grasp.T_Br_Co
                T_E_Co_diff = PyKDL.diff(T_E_Co_before, T_E_Co_after)
                print "T_E_Co_diff: %s"%(T_E_Co_diff)
            else:
                print "we can't see the object!"

            grip.success()

            grips_db.append( grip )

            raw_input("Press Enter to open fingers...")

            velma.move_hand_client((0,0,0,0), v=(1.2, 1.2, 1.2, 1.2), t=(3000.0, 3000.0, 3000.0, 3000.0))
            if velma.checkStopCondition(3.0):
                break

            duration = velma.getMovementTime(velma_init_T_B_W, max_v_l=0.1, max_v_r=0.2)
            velma.moveWrist2(velma_init_T_B_W*velma.T_W_T)
            raw_input("Press Enter to move back to initial position in " + str(duration) + " s...")
            if velma.checkStopCondition():
                break
            velma.moveWrist(velma_init_T_B_W, duration, Wrench(Vector3(20,20,20), Vector3(4,4,4)), abort_on_q5_singularity=True, abort_on_q5_q6_self_collision=True)
            if velma.checkStopCondition(duration):
                break

        # grasping loop end

        for grip in grips_db:
            grip.serializePrint()

        print "setting stiffness to very low value"
        velma.moveImpedance(velma.k_error, 0.5)
        if velma.checkStopCondition(0.5):
            exit(0)

        while not rospy.is_shutdown():
            rospy.sleep(1.0)

        exit(0)

if __name__ == '__main__':

    rospy.init_node('grasp_leanring')

    global br
    pub_marker = velmautils.MarkerPublisher()
    task = GraspingTask(pub_marker)
    rospy.sleep(1)
    br = tf.TransformBroadcaster()

    task.spin()


