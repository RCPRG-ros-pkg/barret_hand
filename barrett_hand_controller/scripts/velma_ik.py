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

from urdf_parser_py.urdf import URDF
from pykdl_utils.kdl_parser import kdl_tree_from_urdf_model
from velma import Velma
import pose_lookup_table as plut

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

def publishSinglePointMarker(pt, i, r=1, g=0, b=0, namespace='default', frame_id='torso_base', m_type=Marker.CUBE, scale=Vector3(0.005, 0.005, 0.005), orientation=Quaternion(0,0,0,1)):
    m = MarkerArray()
    marker = Marker()
    marker.header.frame_id = frame_id
    marker.header.stamp = rospy.Time.now()
    marker.ns = namespace
    marker.id = i
    marker.type = m_type
    marker.action = 0
    marker.pose = Pose( Point(pt.x(),pt.y(),pt.z()), orientation )
    marker.scale = scale
    marker.color = ColorRGBA(r,g,b,0.5)
    m.markers.append(marker)
    pub_marker.publish(m)

def publishMultiPointsMarker(pt, r=1, g=0, b=0, namespace='default', frame_id='torso_base', m_type=Marker.CUBE, scale=Vector3(0.002, 0.002, 0.002)):
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
    pub_marker.publish(m)

def publishVectorMarker(v1, v2, i, r, g, b, frame='torso_base', namespace='default'):
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

    pub_marker.publish(m)

def getAngle(v1, v2):
    return math.atan2((v1*v2).Norm(), PyKDL.dot(v1,v2))

def drawDodecahedronFace(fr, a, i_base, name):
    # radius of the inscribed sphere
    r_i = a * 0.5 * math.sqrt(5.0/2.0 + 11.0/10.0*math.sqrt(5.0))

    R = 2.0 * a / math.sqrt(2.0*(5.0-math.sqrt(5.0)))

    # generate vertices
    v = []
    for i in range(0,5):
        v.append(PyKDL.Vector(R*math.cos(i*72.0/180.0*math.pi), R*math.sin(i*72.0/180.0*math.pi), r_i))

    i = 0
    # draw vertices
    for pt in v:
        publishSinglePointMarker(fr*pt, i_base+i, r=1, g=0, b=0, namespace=name, frame_id='torso_base', m_type=Marker.CUBE, scale=Vector3(0.005, 0.005, 0.005))
        i += 1

    q = fr.M.GetQuaternion()
    center = PyKDL.Vector(0,0,r_i)
    publishSinglePointMarker(fr*center, i_base+i, r=0.5, g=0.5, b=0.5, namespace=name, frame_id='torso_base', m_type=Marker.CUBE, scale=Vector3(a, a, 0.001), orientation=Quaternion(q[0],q[1],q[2],q[3]))
    i += 1
    # draw axes
    publishVectorMarker(fr*center, fr*(center+PyKDL.Vector(a,0,0)), i_base+i, 1, 0, 0, frame='torso_base', namespace=name)
    i += 1
    publishVectorMarker(fr*center, fr*(center+PyKDL.Vector(0,a,0)), i_base+i, 0, 1, 0, frame='torso_base', namespace=name)
    i += 1
    publishVectorMarker(fr*center, fr*(center+PyKDL.Vector(0,0,a)), i_base+i, 0, 0, 1, frame='torso_base', namespace=name)
    i += 1

    return i_base+i

def generateRotationsForDodecahedron():
    angle = 72.0/180.0*math.pi
    dihedral_angle = math.acos(-1.0/math.sqrt(5.0))
    dihedral_transform_angle = math.pi - dihedral_angle

    i = 0
    fr1 = PyKDL.Frame()
#    i = drawDodecahedronFace(fr1, 0.1, i, "fr1")

    fr2 = fr1 * PyKDL.Frame( PyKDL.Rotation.RotY(-dihedral_transform_angle) ) * PyKDL.Frame( PyKDL.Rotation.RotZ(angle/2.0) )
#    i = drawDodecahedronFace(fr2, 0.1, i, "fr2")

    fr3 = fr2 * PyKDL.Frame( PyKDL.Rotation.RotY(-dihedral_transform_angle) ) * PyKDL.Frame( PyKDL.Rotation.RotZ(angle/2.0) )
#    i = drawDodecahedronFace(fr3, 0.1, i, "fr3")

    fr4 = fr3 * PyKDL.Frame( PyKDL.Rotation.RotY(-dihedral_transform_angle) ) * PyKDL.Frame( PyKDL.Rotation.RotZ(angle/2.0) )
#    i = drawDodecahedronFace(fr4, 0.1, i, "fr4")

    fr5 = fr4 * PyKDL.Frame( PyKDL.Rotation.RotY(-dihedral_transform_angle) ) * PyKDL.Frame( PyKDL.Rotation.RotZ(angle/2.0) )
#    i = drawDodecahedronFace(fr5, 0.1, i, "fr5")

    fr6 = fr1 * PyKDL.Frame( PyKDL.Rotation.RotZ(angle) ) * PyKDL.Frame( PyKDL.Rotation.RotY(-dihedral_transform_angle) ) * PyKDL.Frame( PyKDL.Rotation.RotZ(angle/2.0) )
#    i = drawDodecahedronFace(fr6, 0.1, i, "fr6")

    fr7 = fr1 * PyKDL.Frame( PyKDL.Rotation.RotZ(-angle) ) * PyKDL.Frame( PyKDL.Rotation.RotY(-dihedral_transform_angle) ) * PyKDL.Frame( PyKDL.Rotation.RotZ(angle/2.0) )
#    i = drawDodecahedronFace(fr7, 0.1, i, "fr7")

    fr8 = fr7 * PyKDL.Frame( PyKDL.Rotation.RotY(-dihedral_transform_angle) ) * PyKDL.Frame( PyKDL.Rotation.RotZ(angle/2.0) )
#    i = drawDodecahedronFace(fr8, 0.1, i, "fr8")

    fr9 = fr8 * PyKDL.Frame( PyKDL.Rotation.RotZ(-angle) ) * PyKDL.Frame( PyKDL.Rotation.RotY(-dihedral_transform_angle) ) * PyKDL.Frame( PyKDL.Rotation.RotZ(angle/2.0) )
#    i = drawDodecahedronFace(fr9, 0.1, i, "fr9")

    fr10 = fr9 * PyKDL.Frame( PyKDL.Rotation.RotZ(-angle) ) * PyKDL.Frame( PyKDL.Rotation.RotY(-dihedral_transform_angle) ) * PyKDL.Frame( PyKDL.Rotation.RotZ(angle/2.0) )
#    i = drawDodecahedronFace(fr10, 0.1, i, "fr10")

    fr11 = fr10 * PyKDL.Frame( PyKDL.Rotation.RotZ(-angle) ) * PyKDL.Frame( PyKDL.Rotation.RotY(-dihedral_transform_angle) ) * PyKDL.Frame( PyKDL.Rotation.RotZ(angle/2.0) )
#    i = drawDodecahedronFace(fr11, 0.1, i, "fr11")

    fr12 = fr11 * PyKDL.Frame( PyKDL.Rotation.RotZ(-2.0*angle) ) * PyKDL.Frame( PyKDL.Rotation.RotY(-dihedral_transform_angle) ) * PyKDL.Frame( PyKDL.Rotation.RotZ(angle/2.0) )
#    i = drawDodecahedronFace(fr12, 0.1, i, "fr12")

    frames = []
    frames.append(fr1)
    frames.append(fr2)
    frames.append(fr3)
    frames.append(fr4)
    frames.append(fr5)
    frames.append(fr6)
    frames.append(fr7)
    frames.append(fr8)
    frames.append(fr9)
    frames.append(fr10)
    frames.append(fr11)
    frames.append(fr12)

    ret = []
    for f in frames:
        ret.append( copy.deepcopy(f.M) )
        ret.append( copy.deepcopy((f*PyKDL.Frame(PyKDL.Rotation.RotZ(angle))).M) )
        ret.append( copy.deepcopy((f*PyKDL.Frame(PyKDL.Rotation.RotZ(2.0*angle))).M) )
        ret.append( copy.deepcopy((f*PyKDL.Frame(PyKDL.Rotation.RotZ(3.0*angle))).M) )
        ret.append( copy.deepcopy((f*PyKDL.Frame(PyKDL.Rotation.RotZ(4.0*angle))).M) )

#    i = 0
#    for f in ret:
#        # draw axes
#        publishVectorMarker(PyKDL.Vector(), f*PyKDL.Vector(0.1,0,0), i, 1, 0, 0, frame='torso_base', namespace='default')
#        i += 1
#        publishVectorMarker(PyKDL.Vector(), f*PyKDL.Vector(0,0.1,0), i, 0, 1, 0, frame='torso_base', namespace='default')
#        i += 1
#        publishVectorMarker(PyKDL.Vector(), f*PyKDL.Vector(0,0,0.1), i, 0, 0, 1, frame='torso_base', namespace='default')
#        i += 1

    return ret

def calculateIk(step, x_min, x_max, y_min, y_max, z_min, z_max, pt_c_in_T2, min_dist, max_dist):
    min_dist2 = min_dist*min_dist
    max_dist2 = max_dist*max_dist

    robot = URDF.from_parameter_server()
    tree = kdl_tree_from_urdf_model(robot)
    print tree.getNrOfSegments()

    chain = tree.getChain("torso_link2", "right_HandPalmLink")
    print chain.getNrOfJoints()

# from velma_controller.launch:
# upper_limit: [100.0, 100.0, 2.96, 2.09, 2.96, 2.09, 2.96, 2.09, 2.96, 2.96, 2.09, 2.96, 2.09, 2.96, 2.09, 2.96]
# lower_limit: [-100.0, -100.0, -2.96, -2.09, -2.96, -2.09, -2.96, -2.09, -2.96, -2.96, -2.09, -2.96, -2.09, -2.96, -2.09, -2.96]
# joint_names: [torso_0_joint, torso_1_joint, right_arm_0_joint, right_arm_1_joint, right_arm_2_joint, right_arm_3_joint, right_arm_4_joint, right_arm_5_joint, right_arm_6_joint, left_arm_0_joint, left_arm_1_joint, left_arm_2_joint, left_arm_3_joint, left_arm_4_joint, left_arm_5_joint, left_arm_6_joint]

# 2.96, 2.09, 2.96, 2.09, 2.96, 2.09, 2.96
# -2.96, -2.09, -2.96, -2.09, -2.96, -2.09, -2.96
# right_arm_0_joint, right_arm_1_joint, right_arm_2_joint, right_arm_3_joint, right_arm_4_joint, right_arm_5_joint, right_arm_6_joint
    q_min = PyKDL.JntArray(7)#[-2.96, -2.09, -2.96, -2.09, -2.96, -2.09, -2.96]
    q_max = PyKDL.JntArray(7)#[2.96, 2.09, 2.96, 2.09, 2.96, 2.09, 2.96]
    q_limit = 0.26*0.1
    q_min[0] = -2.96 + q_limit
    q_min[1] = -2.09 + q_limit
    q_min[2] = -2.96 + q_limit
    q_min[3] = -2.09 + q_limit
    q_min[4] = -2.96 + q_limit
    q_min[5] = -2.09 + q_limit
    q_min[6] = -2.96 + q_limit
    q_max[0] = 2.96 - q_limit
    q_max[1] = 2.09 - q_limit
    q_max[2] = 2.96 - q_limit
    q_max[3] = 2.09 - q_limit
    q_max[4] = 2.96 - q_limit
    q_max[5] = 2.09 - q_limit
    q_max[6] = 2.96 - q_limit
    fk_solver = PyKDL.ChainFkSolverPos_recursive(chain)
    vel_ik_solver = PyKDL.ChainIkSolverVel_pinv(chain)
    ik_solver = PyKDL.ChainIkSolverPos_NR_JL(chain, q_min, q_max, fk_solver, vel_ik_solver, 100)

#name: ['torso_0_joint', 'torso_1_joint', 'right_arm_0_joint', 'right_arm_1_joint', 'right_arm_2_joint', 'right_arm_3_joint', 'right_arm_4_joint', 'right_arm_5_joint', 'right_arm_6_joint', 'left_arm_0_joint', 'left_arm_1_joint', 'left_arm_2_joint', 'left_arm_3_joint', 'left_arm_4_joint', 'left_arm_5_joint', 'left_arm_6_joint']
#position: [0.01879189377789692, -1.5707963267948966, -1.256859302520752, 1.4936097860336304, -1.429112434387207, 1.8518760204315186, 0.12087352573871613, -1.626944661140442, 1.7902963161468506, -1.7999240159988403, -1.8513352870941162, 1.6786730289459229, -1.1203926801681519, 0.0015585091896355152, 1.8605016469955444, 1.3599008321762085]

    q_init = PyKDL.JntArray(7)
    q_init[0] = -1.256859302520752
    q_init[1] = 1.4936097860336304
    q_init[2] = -1.429112434387207
    q_init[3] = 1.8518760204315186
    q_init[4] = 0.12087352573871613
    q_init[5] = -1.626944661140442
    q_init[6] = 1.7902963161468506

    q_out = PyKDL.JntArray(7)

    x_set = np.arange(x_min, x_max, step)
    y_set = np.arange(y_min, y_max, step)
    z_set = np.arange(z_min, z_max, step)
    print "#length: %s"%(len(x_set)*len(y_set)*len(z_set))
    print "rotations=["
    for r in rot:
        q = r.GetQuaternion()
        print "PyKDL.Rotation.Quaternion(%s,%s,%s,%s),"%(q[0],q[1],q[2],q[3])
    print "]"
    print "x_set=["
    for x in x_set:
        print "%s,"%(x)
    print "]"
    print "y_set=["
    for x in y_set:
        print "%s,"%(x)
    print "]"
    print "z_set=["
    for x in z_set:
        print "%s,"%(x)
    print "]"

    print "lookup_table=["
    for x in x_set:
        print "# x=%s"%(x)
        print "["
        if rospy.is_shutdown():
            break
        y = 0
        for y in y_set:
            print "# y=%s"%(y)
            print "["
            for z in z_set:
                print "["
                if rospy.is_shutdown():
                    break
                rot_index = 0
                dist = (pt_c_in_T2.x()-x)*(pt_c_in_T2.x()-x) + (pt_c_in_T2.y()-y)*(pt_c_in_T2.y()-y) + (pt_c_in_T2.z()-z)*(pt_c_in_T2.z()-z)
                if dist <= max_dist2 and dist >= min_dist2:
                    for r in rot:
                        fr = PyKDL.Frame(r, PyKDL.Vector(x,y,z))
                        status = ik_solver.CartToJnt(q_init, fr, q_out)
                        if status == 0:
                            print "%s,"%(rot_index)
                        rot_index += 1
                else:
                    print "# skipped"
                print "],"
            print "],"
        print "],"
    print "]"

    print "# successfully generated"

if __name__ == '__main__':

    # literature:
    # https://github.com/orocos/orocos_kinematics_dynamics/blob/master/python_orocos_kdl/PyKDL/kinfam.sip
    # http://wiki.ros.org/pykdl_utils
    # https://github.com/gt-ros-pkg/hrl-kdl/blob/hydro/pykdl_utils/src/pykdl_utils/kdl_parser.py
    # http://people.mech.kuleuven.be/~rsmits/kdl/api/html/annotated.html
    # http://people.mech.kuleuven.be/~rsmits/kdl/api/html/classKDL_1_1ChainIkSolverPos__NR__JL.html

    # to read:
    # https://github.com/benersuay/rmaps
    # http://www.dlr.de/rmc/rm/Portaldata/52/Resources/images/institute/robotersysteme/rollin_justin/mobile_manipulation/leidner2014object.pdf

    # test: move the gripper around
    if False:
        rospy.init_node('velma_ik_test')
        global pub_marker
        pub_marker = rospy.Publisher('/door_markers', MarkerArray)
        rospy.sleep(1)

        x_min = 0.1
        x_max = 1.0
        y_min = -0.4
        y_max = 1.0
        z_min = -0.4
        z_max = 1.2
        publishSinglePointMarker(PyKDL.Vector((x_min+x_max)/2.0, (y_min+y_max)/2.0, (z_min+z_max)/2.0), 0, r=1, g=1, b=1, namespace='default', frame_id="torso_link2", m_type=Marker.CUBE, scale=Vector3(x_max-x_min, y_max-y_min, z_max-z_min))

        velma = Velma()
        while not rospy.is_shutdown():
            velma.updateTransformations()
            T_B_E = velma.T_B_W * velma.T_W_E
            print velma.isFramePossible(T_B_E)
            rospy.sleep(0.5)
        exit(0)

    # test: draw the border of the workspace
    if False:
        rospy.init_node('velma_ik_draw_workspace_border')
        global pub_marker
        pub_marker = rospy.Publisher('/door_markers', MarkerArray)
        rospy.sleep(1)

        i = 0
        x_i = 0
        for x in plut.x_set[0:-2]:
            if rospy.is_shutdown():
                break
            y_i = 0
            for y in plut.y_set[0:-2]:
                if rospy.is_shutdown():
                    break
                z_i = 0
                for z in plut.z_set[0:-2]:
                    l = len(plut.lookup_table[x_i][y_i][z_i])
                    lx = len(plut.lookup_table[x_i+1][y_i][z_i])
                    ly = len(plut.lookup_table[x_i][y_i+1][z_i])
                    lz = len(plut.lookup_table[x_i][y_i][z_i+1])
                    if l == 0 and lx > 0:
                        publishSinglePointMarker(PyKDL.Vector(x,y,z), i, r=1, g=1, b=1, namespace='default', frame_id="torso_link2", m_type=Marker.CUBE)
                        i += 1
                    elif l > 0 and lx == 0:
                        publishSinglePointMarker(PyKDL.Vector(x,y,z), i, r=1, g=1, b=1, namespace='default', frame_id="torso_link2", m_type=Marker.CUBE)
                        i += 1
                    elif l == 0 and ly > 0:
                        publishSinglePointMarker(PyKDL.Vector(x,y,z), i, r=1, g=1, b=1, namespace='default', frame_id="torso_link2", m_type=Marker.CUBE)
                        i += 1
                    elif l > 0 and ly == 0:
                        publishSinglePointMarker(PyKDL.Vector(x,y,z), i, r=1, g=1, b=1, namespace='default', frame_id="torso_link2", m_type=Marker.CUBE)
                        i += 1
                    elif l == 0 and lz > 0:
                        publishSinglePointMarker(PyKDL.Vector(x,y,z), i, r=1, g=1, b=1, namespace='default', frame_id="torso_link2", m_type=Marker.CUBE)
                        i += 1
                    elif l > 0 and lz == 0:
                        publishSinglePointMarker(PyKDL.Vector(x,y,z), i, r=1, g=1, b=1, namespace='default', frame_id="torso_link2", m_type=Marker.CUBE)
                        i += 1
                    z_i += 1
                y_i += 1
            x_i += 1
        print i
        rospy.sleep(3)
        exit(0)   

    # test: draw the workspace
    if True:
        rospy.init_node('velma_ik_draw_workspace')
        global pub_marker
        pub_marker = rospy.Publisher('/door_markers', MarkerArray)
        rospy.sleep(1)

        velma = Velma()
        velma.updateTransformations()
        T_T2_L2 = velma.T_T2_B * velma.T_B_L2
        pt_c_in_T2 = T_T2_L2 * PyKDL.Vector()
        max_dist = 0.0
        min_dist = 10000.0
        i = 0
        x_i = 0
        for x in plut.x_set:
            if rospy.is_shutdown():
                break
            y_i = 0
            for y in plut.y_set:
                if rospy.is_shutdown():
                    break
                z_i = 0
                for z in plut.z_set:
                    l = len(plut.lookup_table[x_i][y_i][z_i])
                    if l > 0:
                        dist = (pt_c_in_T2.x()-x)*(pt_c_in_T2.x()-x) + (pt_c_in_T2.y()-y)*(pt_c_in_T2.y()-y) + (pt_c_in_T2.z()-z)*(pt_c_in_T2.z()-z)
                        if dist > max_dist:
                            max_dist = dist
                        if dist < min_dist:
                            min_dist = dist
                        size = float(l)/60.0
                        publishSinglePointMarker(PyKDL.Vector(x,y,z), i, r=1, g=1, b=1, namespace='default', frame_id="torso_link2", m_type=Marker.SPHERE, scale=Vector3(0.05*size, 0.05*size, 0.05*size))
                        i += 1
                    z_i += 1
                y_i += 1
            rospy.sleep(0.1)
            x_i += 1
        print i
        print math.sqrt(min_dist)
        print math.sqrt(max_dist)
        rospy.sleep(3)
        exit(0)   

    # test: search for the biggest orientation error
    if False:
        rospy.init_node('velma_ik_test3')
        global pub_marker
        pub_marker = rospy.Publisher('/door_markers', MarkerArray)
        rospy.sleep(1)

        velma = Velma()

        max_twist = 0.0
        while not rospy.is_shutdown():
            current_rot = PyKDL.Rotation.RotX((random.random()-0.5)*math.pi*2.0)*PyKDL.Rotation.RotY((random.random()-0.5)*math.pi*2.0)*PyKDL.Rotation.RotZ((random.random()-0.5)*math.pi*2.0)
            min_twist = velma.getClosestRotation(plut.rotations, current_rot)
            if min_twist > max_twist:
                max_twist = min_twist
                print max_twist
#            i = 0
#            for c_i in closest_i:
#                i = drawDodecahedronFace(PyKDL.Frame(plut.rotations[c_i]), 0.1, i, 'default')
#            # draw axes
#            publishVectorMarker(PyKDL.Vector(), PyKDL.Frame(current_rot)*PyKDL.Vector(0.1,0,0), i, 1, 0, 0, frame='torso_base', namespace='default')
#            i += 1
#            publishVectorMarker(PyKDL.Vector(), PyKDL.Frame(current_rot)*PyKDL.Vector(0,0.1,0), i, 0, 1, 0, frame='torso_base', namespace='default')
#            i += 1
#            publishVectorMarker(PyKDL.Vector(), PyKDL.Frame(current_rot)*PyKDL.Vector(0,0,0.1), i, 0, 0, 1, frame='torso_base', namespace='default')
#            i += 1
#            raw_input("Press Enter to continue...")
#            angle += 5.0/180.0*math.pi
        exit(0)

    # discretize the space
    if False:
        rospy.init_node('velma_ik_solver')
        global pub_marker
        pub_marker = rospy.Publisher('/door_markers', MarkerArray)
        rospy.sleep(1)

        velma = Velma()
        velma.updateTransformations()
        T_T2_L2 = velma.T_T2_B * velma.T_B_L2
        pt_c_in_T2 = T_T2_L2 * PyKDL.Vector()
        min_dist = 0.330680893438 - 0.05
        max_dist = 0.903499165003 + 0.05

        print "#!/usr/bin/env python"
        print "import PyKDL"

        rot = generateRotationsForDodecahedron()
        print "# number of rotations: %s"%(len(rot))
        x_min = 0.1
        x_max = 1.0
        y_min = -0.4
        y_max = 1.0
        z_min = -0.4
        z_max = 1.2
        publishSinglePointMarker(PyKDL.Vector((x_min+x_max)/2.0, (y_min+y_max)/2.0, (z_min+z_max)/2.0), 0, r=1, g=1, b=1, namespace='default', frame_id="torso_link2", m_type=Marker.CUBE, scale=Vector3(x_max-x_min, y_max-y_min, z_max-z_min))
        calculateIk(0.025, x_min, x_max, y_min, y_max, z_min, z_max, pt_c_in_T2, min_dist, max_dist)
        exit(0)


