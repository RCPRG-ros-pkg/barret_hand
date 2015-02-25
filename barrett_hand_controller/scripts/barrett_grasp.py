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

import ar_track_alvar_msgs.msg
from ar_track_alvar_msgs.msg import *
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
from velma import Velma
from velmasim import VelmaSim
import random
from openravepy import *
#from ..openravepy_int import KinBody, TriMesh
from openravepy.openravepy_int import KinBody, TriMesh

from optparse import OptionParser
from openravepy.misc import OpenRAVEGlobalArguments
import velmautils
import surfaceutils
import openraveinstance
import itertools
import dijkstra
import grip
import operator

from optparse import OptionParser
from openravepy.misc import OpenRAVEGlobalArguments
from interactive_markers.interactive_marker_server import *
from interactive_markers.menu_handler import *

import ode
import xode.transform

class GraspingTask:
    """
Class for grasp learning.
"""

    def __init__(self, pub_marker=None):
        self.pub_marker = pub_marker
        self.listener = tf.TransformListener();
        # create an interactive marker server on the topic namespace simple_marker
        self.mk_server = InteractiveMarkerServer('obj_pose_markers')

    def addBox(self, name, x_size, y_size, z_size):
        body = RaveCreateKinBody(self.env,'')
        body.SetName(name)
        body.InitFromBoxes(numpy.array([[0,0,0,0.5*x_size,0.5*y_size,0.5*z_size]]),True)
        self.env.Add(body,True)

    def addSphere(self, name, size):
        body = RaveCreateKinBody(self.env,'')
        body.SetName(name)
        body.InitFromSpheres(numpy.array([[0,0,0,0.5*size]]),True)
        self.env.Add(body,True)

    def addTrimesh(self, name, vertices, faces):
        body = RaveCreateKinBody(self.env,'')
        body.SetName(name)
        mesh = TriMesh()
        mesh.vertices = copy.deepcopy(vertices)
        mesh.indices = copy.deepcopy(faces)
        body.InitFromTrimesh(mesh, True)
        self.env.Add(body,True)

    def KDLToOpenrave(self, T):
        ret = numpy.array([
        [T.M[0,0], T.M[0,1], T.M[0,2], T.p.x()],
        [T.M[1,0], T.M[1,1], T.M[1,2], T.p.y()],
        [T.M[2,0], T.M[2,1], T.M[2,2], T.p.z()],
        [0, 0, 0, 1]])
        return ret

    def OpenraveToKDL(self, T):
        rot = PyKDL.Rotation(T[0][0],T[0][1],T[0][2],T[1][0],T[1][1],T[1][2],T[2][0],T[2][1],T[2][2])
        pos = PyKDL.Vector(T[0][3], T[1][3], T[2][3])
        return PyKDL.Frame(rot, pos)

    def updatePose(self, name, T_Br_Bo):
        with self.env:
            body = self.env.GetKinBody(name)
            if body != None:
                body.SetTransform(self.KDLToOpenrave(T_Br_Bo))
            else:
#                print "openrave: could not find body: %s"%(name)
                pass
            self.env.UpdatePublishedBodies()

    # spread, f1, f3, f2
    def runGrasp(self, directions, positions):
        contacts = None
        finalconfig = None
        mindist = None
        volume = None
        with self.openrave_robot.CreateRobotStateSaver():
            try:
                    lower_limit, upper_limit = self.openrave_robot.GetDOFLimits()
                    pos = []
                    for i in range(4):
                        if directions[i] > 0.0:
                            pos.append(lower_limit[i]+0.001)
                        elif directions[i] < 0.0:
                            pos.append(upper_limit[i]-0.051)
                        else:
                            pos.append(positions[i])

                    self.openrave_robot.GetActiveManipulator().SetChuckingDirection(directions)
                    target = self.env.GetKinBody("object")
                    self.openrave_robot.SetDOFValues(pos)

                    contacts,finalconfig,mindist,volume = self.grasper.Grasp(execute=False, outputfinal=True, transformrobot=False, target=target)
                    
            except e:
                print "runGrasp: planning error:"
                print e
        return contacts,finalconfig,mindist,volume

    def getGraspQHull(self, points):
        try:
            planes, faces, triangles = self.grasper.ConvexHull(np.array(points), returnplanes=True,returnfaces=False,returntriangles=False)
        except:
            return None
        return planes

    def contactToWrenches(self, pos, normal, friction, Nconepoints):
            wrenches = []
            fdeltaang = 2.0*math.pi/float(Nconepoints)
            nz = normal
            if abs(nz.z()) < 0.7:
                nx = PyKDL.Vector(0,0,1)
            elif abs(nz.y()) < 0.7:
                nx = PyKDL.Vector(0,1,0)
            else:
                nx = PyKDL.Vector(1,0,0)
            ny = nz * nx
            nx = ny * nz
            nx.Normalize()
            ny.Normalize()
            nz.Normalize()
            R_n = PyKDL.Frame(PyKDL.Rotation(nx,ny,nz))
            fangle = 0.0
            for cp in range(Nconepoints):
                nn = R_n * PyKDL.Frame(PyKDL.Rotation.RotZ(fangle)) * PyKDL.Vector(friction,0,1)
                fangle += fdeltaang
                tr = pos * nn
                wr = PyKDL.Wrench(nn,tr)
                wrenches.append([wr[0], wr[1], wr[2], wr[3], wr[4], wr[5]])
            return wrenches

    def generateGWS(self, contacts, friction):
        qhullpoints = []
        qhullpoints_contact_idx = []
        contact_idx = 0
        for c in contacts:
            p = PyKDL.Vector(c[0], c[1], c[2])
            nz = PyKDL.Vector(c[3], c[4], c[5])
            wrs = self.contactToWrenches(p, nz, friction, 6)
            for wr in wrs:
                qhullpoints.append([wr[0], wr[1], wr[2], wr[3], wr[4], wr[5]])
                qhullpoints_contact_idx.append(contact_idx)
            contact_idx += 1

        qhullplanes = self.getGraspQHull(qhullpoints)
        qhullplanes_contacts = []
        contact_planes = []
        for pl in qhullplanes:
            qhullplanes_contacts.append([])

        for c in contacts:
            contact_planes.append([])

        for pt_idx in range(len(qhullpoints)):
            pt = qhullpoints[pt_idx]
            contact_idx = qhullpoints_contact_idx[pt_idx]

            for pl_idx in range(len(qhullplanes)):
                pl = qhullplanes[pl_idx]
                dist = pl[0] * pt[0] + pl[1] * pt[1] + pl[2] * pt[2] + pl[3] * pt[3] + pl[4] * pt[4] + pl[5] * pt[5] + pl[6]
                if abs(dist) < 0.00000001 and not contact_idx in qhullplanes_contacts[pl_idx]:
                    qhullplanes_contacts[pl_idx].append(contact_idx)
                    contact_planes[contact_idx].append(pl_idx)

#        for contact_idx in range(len(contacts)):
#            print contact_planes[contact_idx]

#        for pl_idx in range(len(qhullplanes)):
#            print qhullplanes_contacts[pl_idx]

        return qhullplanes, contact_planes

    def reduceContacts(self, contacts):
        max_angle = 15.0/180*math.pi
        max_n_dist = 2.0 * math.sin(max_angle/2.0)
        max_pos_dist = 0.003
        removed_ids = []
        reduced_contacts = []
        for c1_id in range(len(contacts)):
            if c1_id in removed_ids:
                continue
            removed_ids.append(c1_id)
            c1 = contacts[c1_id]
            reduced_contacts.append(c1)
            c1_pos = PyKDL.Vector(c1[0], c1[1], c1[2])
            c1_n = PyKDL.Vector(c1[3], c1[4], c1[5])
            for c2_id in range(c1_id+1, len(contacts)):
                if c2_id in removed_ids:
                    continue
                c2 = contacts[c2_id]
                c2_pos = PyKDL.Vector(c2[0], c2[1], c2[2])
                c2_n = PyKDL.Vector(c2[3], c2[4], c2[5])
                if (c1_pos-c2_pos).Norm() < max_pos_dist and (c1_n-c2_n).Norm() < max_n_dist:
                    removed_ids.append(c2_id)

        return reduced_contacts                    

        dist = np.zeros((len(contacts),len(contacts)))
        for c1_id in range(len(contacts)):
            c1 = contacts[c1_id]
            c1_pos = PyKDL.Vector(c1[0], c1[1], c1[2])
            c1_n = PyKDL.Vector(c1[3], c1[4], c1[5])
            for c2_id in range(0, c1_id):
                c2 = contacts[c2_id]
                c2_pos = PyKDL.Vector(c2[0], c2[1], c2[2])
                c2_n = PyKDL.Vector(c2[3], c2[4], c2[5])

                dist[c1_id][c2_id] = (c1_pos-c2_pos).Norm()/max_pos_dist + (c1_n-c2_n).Norm()/max_n_dist



    def createInteractiveMarkerControl6DOF(self, mode, axis):
        control = InteractiveMarkerControl()
        control.orientation_mode = InteractiveMarkerControl.FIXED
        if mode == InteractiveMarkerControl.ROTATE_AXIS:
            control.name = 'rotate_';
        if mode == InteractiveMarkerControl.MOVE_AXIS:
            control.name = 'move_';
        if axis == 'x':
            control.orientation = Quaternion(1,0,0,1)
            control.name = control.name+'x';
        if axis == 'y':
            control.orientation = Quaternion(0,1,0,1)
            control.name = control.name+'x';
        if axis == 'z':
            control.orientation = Quaternion(0,0,1,1)
            control.name = control.name+'x';
        control.interaction_mode = mode
        return control

    def processFeedback(self, feedback):
        if feedback.event_type == InteractiveMarkerFeedback.BUTTON_CLICK and feedback.control_name == "button":
            self.run_ode_simulation = True

        if feedback.marker_name == 'obj_pose_marker':# and feedback.event_type == InteractiveMarkerFeedback.MOUSE_UP:
            self.T_W_O = pm.fromMsg(feedback.pose)

    def createButtonMarkerControl(self, scale, position):
        marker = Marker()
        marker.type = Marker.SPHERE
        marker.scale = scale
        marker.pose.position = position
        marker.color = ColorRGBA(1,0,0,1)
        control = InteractiveMarkerControl()
        control.always_visible = True;
        control.markers.append( marker );
        return control

    def insert6DofGlobalMarker(self, T_W_M):
        int_position_marker = InteractiveMarker()
        int_position_marker.header.frame_id = 'world'
        int_position_marker.name = 'obj_pose_marker'
        int_position_marker.scale = 0.1
        int_position_marker.pose = pm.toMsg(T_W_M)
        int_position_marker.controls.append(self.createInteractiveMarkerControl6DOF(InteractiveMarkerControl.ROTATE_AXIS,'x'));
        int_position_marker.controls.append(self.createInteractiveMarkerControl6DOF(InteractiveMarkerControl.ROTATE_AXIS,'y'));
        int_position_marker.controls.append(self.createInteractiveMarkerControl6DOF(InteractiveMarkerControl.ROTATE_AXIS,'z'));
        int_position_marker.controls.append(self.createInteractiveMarkerControl6DOF(InteractiveMarkerControl.MOVE_AXIS,'x'));
        int_position_marker.controls.append(self.createInteractiveMarkerControl6DOF(InteractiveMarkerControl.MOVE_AXIS,'y'));
        int_position_marker.controls.append(self.createInteractiveMarkerControl6DOF(InteractiveMarkerControl.MOVE_AXIS,'z'));
        self.mk_server.insert(int_position_marker, self.processFeedback)

        int_button_marker = InteractiveMarker()
        int_button_marker.header.frame_id = 'world'
        int_button_marker.name = 'obj_button_marker'
        int_button_marker.scale = 0.2
        int_button_marker.pose = pm.toMsg(PyKDL.Frame())
        box = self.createButtonMarkerControl(Point(0.05,0.05,0.05), Point(0.0, 0.0, 0.15) )
        box.interaction_mode = InteractiveMarkerControl.BUTTON
        box.name = 'button'
        int_button_marker.controls.append( box )
        self.mk_server.insert(int_button_marker, self.processFeedback)

        self.mk_server.applyChanges()

    def erase6DofMarker(self):
        self.mk_server.erase('obj_pose_marker')
        self.mk_server.applyChanges()

    def getMesh(self, name):
        body = self.env.GetKinBody(name)
        if body == None:
            return None
        link = body.GetLinks()[0]
        col = link.GetCollisionData()
        return col.vertices, col.indices

    def checkNeighbors(self, surface_points, current_id, ref_force, ref_torque, max_force_dist, max_torque_dist):
        force = surface_points[current_id].normal
        if (ref_force-force).Norm() > max_force_dist:
            return []

        torque = surface_points[current_id].pos * surface_points[current_id].normal
        if (ref_torque-torque).Norm() > max_torque_dist:
            return []

        if surface_points[current_id].visited == True:
            return []
        ret_list = [current_id]
        surface_points[current_id].visited = True
        for n_id in surface_points[current_id].neighbors_id:
            ret_list = ret_list + self.checkNeighbors(surface_points, n_id, ref_force, ref_torque, max_force_dist, max_torque_dist)

        return ret_list

    def getContactPointOnSurface(self, surface_points, contact_point):
        min_dist = None
        min_point_id = -1
        for pt in surface_points:
            pt.visited = False
            dist = (pt.pos-contact_point).Norm()
            if min_dist == None or dist < min_dist:
                min_dist = dist
                min_point_id = pt.id
        return min_point_id

    def getContactRegion(self, surface_points, contact_point):
        min_dist = None
        min_point_id = -1
        for pt in surface_points:
            pt.visited = False
            dist = (pt.pos-contact_point).Norm()
            if min_dist == None or dist < min_dist:
                min_dist = dist
                min_point_id = pt.id

        max_force_dist = 0.1
        max_torque_dist = 0.02

        ref_force = surface_points[min_point_id].normal
        ref_torque = surface_points[min_point_id].pos * surface_points[min_point_id].normal

        region = self.checkNeighbors(surface_points, min_point_id, ref_force, ref_torque, max_force_dist, max_torque_dist)
        return region

    def getContactConstraintFn(self, surface_points, current_id, ref_force, ref_torque, max_force_dist, max_torque_dist, contact_point):

        force = surface_points[current_id].normal
        torque = surface_points[current_id].pos * surface_points[current_id].normal
        if (ref_force-force).Norm() > max_force_dist or (ref_torque-torque).Norm() > max_torque_dist:
            dist = (contact_point-surface_points[current_id].pos).Norm()
            if self.getContactConstraint_min_dist == None or self.getContactConstraint_min_dist > dist:
                self.getContactConstraint_min_dist = dist
            return

        if surface_points[current_id].visited == True:
            return

        surface_points[current_id].visited = True
        for n_id in surface_points[current_id].neighbors_id:
            self.getContactConstraintFn(surface_points, n_id, ref_force, ref_torque, max_force_dist, max_torque_dist, contact_point)

        return

    def getContactConstraint(self, surface_points, point_id):
        for pt in surface_points:
            pt.visited = False

        self.getContactConstraint_min_dist = None

        max_force_dist = 0.2
        max_torque_dist = 0.02

        ref_force = surface_points[point_id].normal
        ref_torque = surface_points[point_id].pos * surface_points[point_id].normal

        self.getContactConstraintFn(surface_points, point_id, ref_force, ref_torque, max_force_dist, max_torque_dist, surface_points[point_id].pos)
        return self.getContactConstraint_min_dist

    def getQualituMeasure(self, qhull):
        if qhull == None:
            return 0.0

        mindist = None
        for qp in qhull:
            if qp[6] >= 0:
                return 0
            if mindist == None or mindist > -qp[6]:
                mindist = -qp[6]

        return mindist

    def getQualituMeasure2(self, qhull, wr):
        if qhull == None:
            return 0.0

        wr6 = [wr[0], wr[1], wr[2], wr[3], wr[4], wr[5]]
        mindist = None
        for qp in qhull:
            n = np.array([qp[0],qp[1],qp[2],qp[3],qp[4],qp[5]])
            if np.dot(n,n) > 1.00001 or np.dot(n,n) < 0.9999:
                print "ERROR: getQualituMeasure2: np.dot(n,n): %s"%(np.dot(n,n))
                exit(0)
            dot = np.dot(np.array(wr6), n)
            if dot > 0:
                dqp = -qp[6]/dot
                if mindist == None or mindist > dqp:
                    mindist = dqp
        return mindist

    def transformKdlToOde(self, Tkdl):
        return None
#        print Tkdl
        Tode = xode.transform.Transform()
        for i in range(3):
            for j in range(3):
                Tode.m[j][i] = Tkdl[(j,i)]
        Tode.m[3][0] = Tkdl[(0,3)]
        Tode.m[3][1] = Tkdl[(1,3)]
        Tode.m[3][2] = Tkdl[(2,3)]
#        print Tode.m
        return Tode

    def transformOdeToKdl(self, Tode):
        return None
#        rot = PyKDL.Rotation(
#        Tode.m[0][0], Tode.m[0][1], Tode.m[0][2],
#        Tode.m[1][0], Tode.m[1][1], Tode.m[1][2], 
#        Tode.m[2][0], Tode.m[2][1], Tode.m[2][2])
        rot = PyKDL.Rotation(
        Tode.m[0][0], Tode.m[1][0], Tode.m[2][0],
        Tode.m[0][1], Tode.m[1][1], Tode.m[2][1], 
        Tode.m[0][2], Tode.m[1][2], Tode.m[2][2])
        pos = PyKDL.Vector(Tode.m[3][0], Tode.m[3][1], Tode.m[3][2])
        Tkdl = PyKDL.Frame(rot, pos)
#        print Tkdl
        return Tkdl

    def setOdeBodyPose(self, body, T):
        # in kdl: (x,y,z,w)
        # in ode: (w,x,y,z)
        q = T.M.GetQuaternion()
        body.setPosition( (T.p.x(), T.p.y(), T.p.z()) )
        body.setQuaternion( (q[3], q[0], q[1], q[2]) )
#        body.setRotation((
#        T.M[(0,0)],T.M[(0,1)],T.M[(0,2)],
#        T.M[(1,0)],T.M[(1,1)],T.M[(1,2)],
#        T.M[(2,0)],T.M[(2,1)],T.M[(2,2)] ))
#        body.setRotation((
#        T.M[(0,0)],T.M[(1,0)],T.M[(2,0)],
#        T.M[(0,1)],T.M[(1,1)],T.M[(2,1)],
#        T.M[(0,2)],T.M[(1,2)],T.M[(2,2)] ))

    def getOdeBodyPose(self, body):
        # in kdl: (x,y,z,w)
        # in ode: (w,x,y,z)
        pos = body.getPosition()
        rot = body.getRotation()
#        q = body.getQuaternion()
#        return PyKDL.Frame(PyKDL.Rotation.Quaternion(q[1], q[2], q[3], q[0]), PyKDL.Vector(pos[0], pos[1], pos[2]))
        return PyKDL.Frame(PyKDL.Rotation(
        rot[0], rot[1], rot[2],
        rot[3], rot[4], rot[5],
        rot[6], rot[7], rot[8]),
        PyKDL.Vector(pos[0], pos[1], pos[2]))

    # Collision callback
    def near_callback(self, args, geom1, geom2):
        """Callback function for the collide() method.

        This function checks if the given geoms do collide and
        creates contact joints if they do.
        """

        body1 = geom1.getBody()
        body2 = geom2.getBody()

        if ode.areConnected(body1, body2):
            return

        # Check if the objects do collide
        contacts = ode.collide(geom1, geom2)

        if geom1.name == "object":
            for c in contacts:
                pos, normal, depth, g1, g2 = c.getContactGeomParams()
                self.grasp_contacts.append( (pos[0], pos[1], pos[2], -normal[0], -normal[1], -normal[2]) )

        if geom2.name == "object":
            for c in contacts:
                pos, normal, depth, g1, g2 = c.getContactGeomParams()
                self.grasp_contacts.append( (pos[0], pos[1], pos[2], normal[0], normal[1], normal[2]) )

        # Create contact joints
        world,contactgroup = args
        for c in contacts:
            c.setBounce(0.0)
            c.setMu(5000)
            j = ode.ContactJoint(world, contactgroup, c)
            j.attach(body1, body2)

    def spin(self):
        m_id = 0
        self.pub_marker.eraseMarkers(0,3000, frame_id='world')

        #
        # Init Openrave
        #
        parser = OptionParser(description='Openrave Velma interface')
        OpenRAVEGlobalArguments.addOptions(parser)
        (options, leftargs) = parser.parse_args()
        self.env = OpenRAVEGlobalArguments.parseAndCreate(options)#,defaultviewer=True)

        self.openrave_robot = self.env.ReadRobotXMLFile('robots/barretthand_ros.robot.xml')

        joint_names = []
        print "active joints:"
        for j in self.openrave_robot.GetJoints():
            joint_names.append(j.GetName())
            print j

        print "passive joints:"
        for j in self.openrave_robot.GetPassiveJoints():
            joint_names.append(j.GetName())
            print j

        # ODE does not support distance measure
        self.env.GetCollisionChecker().SetCollisionOptions(CollisionOptions.Contacts)

        self.env.Add(self.openrave_robot)

        vertices, faces = surfaceutils.readStl("klucz_gerda_ascii.stl", scale=1.0)
        self.addTrimesh("object", vertices, faces)

#        self.addBox("object", 0.2,0.06,0.06)
#        self.addSphere("object", 0.15)
#        vertices, faces = self.getMesh("object")

        #
        # definition of the expected external wrenches
        #
        ext_wrenches = []

        # origin of the external wrench (the end point of the key)
        wr_orig = PyKDL.Vector(0.039, 0.0, 0.0)

        for i in range(8):
            # expected force at the end point
            force = PyKDL.Frame(PyKDL.Rotation.RotX(float(i)/8.0 * 2.0 * math.pi)) * PyKDL.Vector(0,1,0)
            # expected torque at the com
            torque = wr_orig * force
            ext_wrenches.append(PyKDL.Wrench(force, torque))

            # expected force at the end point
            force = PyKDL.Frame(PyKDL.Rotation.RotX(float(i)/8.0 * 2.0 * math.pi)) * PyKDL.Vector(-1,1,0)
            # expected torque at the com
            torque = wr_orig * force
            ext_wrenches.append(PyKDL.Wrench(force, torque))

        #
        # definition of the grasps
        #
        grasp_id = 0
        if grasp_id == 0:
            grasp_direction = [0, 1, -1, 1]    # spread, f1, f3, f2
            grasp_initial_configuration = [60.0/180.0*math.pi, None, None, None]
            self.T_W_O = PyKDL.Frame(PyKDL.Rotation.Quaternion(-0.122103662206, -0.124395758838, -0.702726011729, 0.689777190329), PyKDL.Vector(-0.00115787237883, -0.0194999426603, 0.458197712898))
#            self.T_W_O = PyKDL.Frame(PyKDL.Rotation.Quaternion(-0.174202588426, -0.177472708083, -0.691231954612, 0.678495061771), PyKDL.Vector(0.0, -0.0213436260819, 0.459123969078))
        elif grasp_id == 1:
            grasp_direction = [0, 1, -1, 1]    # spread, f1, f3, f2
            grasp_initial_configuration = [90.0/180.0*math.pi, None, None, None]
            self.T_W_O = PyKDL.Frame(PyKDL.Rotation.Quaternion(-0.0187387771868, -0.708157209758, -0.0317875569224, 0.705090018033), PyKDL.Vector(4.65661287308e-10, 0.00145332887769, 0.472836345434))
        elif grasp_id == 2:
            grasp_direction = [0, 1, 0, 0]    # spread, f1, f3, f2
            grasp_initial_configuration = [90.0/180.0*math.pi, None, 90.0/180.0*math.pi, 0]
            self.T_W_O = PyKDL.Frame(PyKDL.Rotation.Quaternion(-0.0187387763947, -0.708157179826, -0.0317875555789, 0.705089928626), PyKDL.Vector(0.0143095180392, 0.00145332887769, 0.483659058809))
        elif grasp_id == 3:
            grasp_direction = [0, 1, 1, 1]    # spread, f1, f3, f2
            grasp_initial_configuration = [90.0/180.0*math.pi, None, None, None]
            self.T_W_O = PyKDL.Frame(PyKDL.Rotation.Quaternion(-0.00518634245761, -0.706548316769, -0.0182458505507, 0.707410947861), PyKDL.Vector(0.000126354629174, -0.00217361748219, 0.47637796402))
        elif grasp_id == 4:
            grasp_direction = [0, 0, 1, 0]    # spread, f1, f3, f2
            grasp_initial_configuration = [90.0/180.0*math.pi, 100.0/180.0*math.pi, None, 100.0/180.0*math.pi]
            self.T_W_O = PyKDL.Frame(PyKDL.Rotation.Quaternion(0.153445252933, -0.161230275653, 0.681741576082, 0.696913201022), PyKDL.Vector(0.000126355327666, 0.00152841210365, 0.466048002243))
        elif grasp_id == 5:
            grasp_direction = [0, 0, 1, 0]    # spread, f1, f3, f2
            grasp_initial_configuration = [100.0/180.0*math.pi, 101.5/180.0*math.pi, None, 101.5/180.0*math.pi]
            self.T_W_O = PyKDL.Frame(PyKDL.Rotation.Quaternion(0.155488650062, -0.159260521271, 0.690572597636, 0.688163302213), PyKDL.Vector(-0.000278688268736, 0.00575117766857, 0.461560428143))
        elif grasp_id == 6:
            grasp_direction = [0, 1, -1, 1]    # spread, f1, f3, f2
            grasp_initial_configuration = [90.0/180.0*math.pi, None, 0, 0]
            self.T_W_O = PyKDL.Frame(PyKDL.Rotation.Quaternion(0.512641041738, -0.485843507183, -0.514213889193, 0.48655882699), PyKDL.Vector(-0.000278423947748, -0.00292747467756, 0.445628076792))
        else:
            print "ERROR: unknown grasp_id: %s"%(grasp_id)
            exit(0)

        self.updatePose("object", self.T_W_O)

        with open('barret_hand_openrave2ros_joint_map2.txt', 'r') as f:
            lines = f.readlines()
            joint_map = {}
            for line in lines:
                line_s = line.split()
                if len(line_s) == 2:
                    joint_map[line_s[0]] = line_s[1]
                elif len(line_s) != 1:
                    print "error in joint map file"
                    exit(0)

        print joint_map

        self.pub_js = rospy.Publisher("/joint_states", JointState)

        # test curvature computation
        if False:
            surfaceutils.testSurfaceCurvature1(self.pub_marker, vertices, faces, self.T_W_O)
            surfaceutils.testSurfaceCurvature2(self.pub_marker, vertices, faces, self.T_W_O)

        if False:

            link = self.openrave_robot.GetLink("right_HandFingerOneKnuckleThreeLink")
            col = link.GetCollisionData()
            vertices = col.vertices
            faces = col.indices

            print "sampling the surface..."
            surface_points = surfaceutils.sampleMeshDetailedRays(vertices, faces, 0.002)
            print "surface has %s points"%(len(surface_points))

            surface_points_init = []
            for sp in surface_points:
                surface_points_init.append(sp)

            p_idx = random.randint(0, len(surface_points)-1)
            p_dist = 0.005

            print "generating a subset of surface points..."

            sampled_points = []
            while True:
                sampled_points.append(p_idx)
                surface_points2 = []
                for sp in surface_points_init:
                    if (sp.pos-surface_points[p_idx].pos).Norm() > p_dist:
                        surface_points2.append(sp)
                if len(surface_points2) == 0:
                    break
                surface_points_init = surface_points2
                p_idx = surface_points_init[0].id

            print "subset size: %s"%(len(sampled_points))

#            points_samp = []
#            points_other = []
#            for pt in surface_points:
#                if pt.id in sampled_points:
#                    points_samp.append(pt.pos)
#                else:
#                    points_other.append(pt.pos)
#            m_id = 0
#            m_id = self.pub_marker.publishMultiPointsMarker(points_samp, m_id, r=0, g=1, b=0, namespace='default', frame_id='world', m_type=Marker.CUBE, scale=Vector3(0.0005, 0.0005, 0.0005), T=self.T_W_O)
#            m_id = self.pub_marker.publishMultiPointsMarker(points_other, m_id, r=1, g=0, b=0, namespace='default', frame_id='world', m_type=Marker.CUBE, scale=Vector3(0.0005, 0.0005, 0.0005), T=self.T_W_O)
#            raw_input("Press ENTER to continue...")
#            exit(0)

#        if True:

            speeds = []
            finger_speeds = (-1, 0, 1)
            for sp in [0]:
             for f1 in finger_speeds:
              for f2 in finger_speeds:
               for f3 in finger_speeds:
                speeds.append((sp, f1, f3, f2))
            print "speeds: %s"%(len(speeds))

            configs = []
#            for sp in np.linspace(0.01, 179.99, 10):
#             for f1 in np.linspace(60.0, 130.0, 7):
#              for f2 in np.linspace(60.0, 130.0, 7):
#               for f3 in np.linspace(60.0, 130.0, 7):

            speeds = [(0,1,-1,1)]
            for sp in [1.04719755/math.pi*180.0]:
             for f1 in [1.63100003/math.pi*180.0]:
              for f2 in [1.62000002/math.pi*180.0]:
               for f3 in [1.91846094/math.pi*180.0]:
                self.openrave_robot.SetDOFValues([sp/180.0*math.pi, f1/180.0*math.pi, f3/180.0*math.pi, f2/180.0*math.pi])
                if not self.openrave_robot.CheckSelfCollision():
                    configs.append((sp/180.0*math.pi, f1/180.0*math.pi, f3/180.0*math.pi, f2/180.0*math.pi))

            print "valid configs of the hand: %s"%(len(configs))

            checked_links = [
            "right_HandFingerOneKnuckleThreeLink",
            "right_HandFingerThreeKnuckleThreeLink",
            "right_HandFingerTwoKnuckleThreeLink",
            ]
            T_W_E = self.OpenraveToKDL(self.openrave_robot.GetLink("right_HandPalmLink").GetTransform())
            TR_W_E = PyKDL.Frame(T_W_E.M)
            T_E_W = T_W_E.Inverse()

            sample_speeds = {}
            print "calculating speeds of the sampled points for all configurations and speeds"
            cf_index = 0
            for cf in configs:
              sample_speeds[cf] = {}
#            cf = [90.0/180.0*math.pi, 70.0/180.0*math.pi, 70.0/180.0*math.pi, 70.0/180.0*math.pi]#configs[1000]
#            if True:
#              for s in speeds:
#              s = [0, 1, 0, 0]#speeds[12]
              for link_name in checked_links:
                sample_speeds[cf][link_name] = {}
                self.openrave_robot.SetDOFValues(cf)
                link = self.openrave_robot.GetLink(link_name)
                T_E_L_1 = T_E_W * self.OpenraveToKDL(link.GetTransform())
                TR_E_L = PyKDL.Frame(T_E_L_1.M)
                for s in finger_speeds:
                  sample_speeds[cf][link_name][s] = {}
                  speed = 0.1
                  self.openrave_robot.SetDOFValues([cf[0], cf[1]+s*speed, cf[2]+s*speed, cf[3]+s*speed])
                  T_E_L_2 = T_E_W * self.OpenraveToKDL(link.GetTransform())
                  for pt_idx in sampled_points:
                      pt = surface_points[pt_idx]
                      sample_speeds[cf][link_name][s][pt_idx] = PyKDL.dot(TR_E_L * pt.normal, (T_E_L_2 * pt.pos) - (T_E_L_1 * pt.pos))
#              print "%s / %s"%(cf_index, len(configs))
              cf_index += 1
            print "done"

            max_radius = 0.015



            relative_contacts = []

            print "calculating relative speed between sampled points on gripper links..."
            cf_index = 0
            for cf in configs:

              self.openrave_robot.SetDOFValues(cf)
              for i in range(0, 2):
                # update the gripper visualization in ros
                js = JointState()
                js.header.stamp = rospy.Time.now()
                for jn in joint_map:
                    js.name.append(joint_map[jn])
                    js.position.append(self.openrave_robot.GetJoint(jn).GetValue(0))
                self.pub_js.publish(js)
                rospy.sleep(0.1)

              for s in speeds:
                pairs = 0
                points = []
                vels = []
                for link_name1_idx in range(0, len(checked_links)):
                  link1_speed_idx = link_name1_idx + 1
                  link_name1 = checked_links[link_name1_idx]
                  link1 = self.openrave_robot.GetLink(link_name1)
                  T_E_L1 = T_E_W * self.OpenraveToKDL(link1.GetTransform())
                  TR_E_L1 = PyKDL.Frame(T_E_L1.M)
                  for link_name2_idx in range(link_name1_idx+1, len(checked_links)):
                    link2_speed_idx = link_name2_idx + 1
                    link_name2 = checked_links[link_name2_idx]
                    link2 = self.openrave_robot.GetLink(link_name2)
                    T_E_L2 = T_E_W * self.OpenraveToKDL(link2.GetTransform())
                    TR_E_L2 = PyKDL.Frame(T_E_L2.M)
                    for pt_idx1 in sampled_points:
                      surf_pt1 = surface_points[pt_idx1]
                      pt1_E = T_E_L1 * surf_pt1.pos
                      vel1 = (sample_speeds[cf][link_name1][s[link1_speed_idx]][pt_idx1]) * (TR_E_L1 * surf_pt1.normal)
                      for pt_idx2 in sampled_points:
                        surf_pt2 = surface_points[pt_idx2]
                        pt2_E = T_E_L2 * surf_pt2.pos
                        vel2 = (sample_speeds[cf][link_name2][s[link2_speed_idx]][pt_idx2]) * (TR_E_L2 * surf_pt2.normal)
                        if PyKDL.dot(vel1-vel2, TR_E_L1 * surf_pt1.normal) > 0.005 and PyKDL.dot(vel2-vel1, TR_E_L2 * surf_pt2.normal) > 0.005:
                          pairs += 1
                          pt1_W = T_W_E * pt1_E
                          pt2_W = T_W_E * pt2_E
                          pos_diff = pt1_W-pt2_W
                          if not pt1_W in points:
                            relative_contacts.append([pos_diff.Norm(), pt1_W, pt2_W])
                            points.append(pt1_W)
                            vels.append(TR_W_E * vel1)
                          if not pt2_W in points:
                            relative_contacts.append([pos_diff.Norm(), pt2_W, pt1_W])
                            points.append(pt2_W)
                            vels.append(TR_W_E * vel2)
              print "%s / %s"%(cf_index, len(configs))
              print "relative_contacts: %s"%(len(relative_contacts))
              cf_index += 1

#            print relative_contacts
            print pairs
            print len(points)
            m_id = 0
            m_id = self.pub_marker.publishMultiPointsMarker(points, m_id, r=1, g=0, b=0, namespace='default', frame_id='world', m_type=Marker.CUBE, scale=Vector3(0.001, 0.001, 0.001), T=None)
            for i in range(len(vels)):
              m_id = self.pub_marker.publishVectorMarker(points[i], points[i]+vels[i]*1, m_id, 0, 0, 1, frame='world', namespace='default', scale=0.001)

#            for rc in relative_contacts:
#              m_id = self.pub_marker.publishVectorMarker(rc[1], rc[2], m_id, 0, 0, 1, frame='world', namespace='default', scale=0.001)

            rospy.sleep(1.0)

            exit(0)


















        #
        # PyODE test
        #
        if True:

            fixed_joints_names_for_fixed_DOF = [
            ["right_HandFingerOneKnuckleOneJoint", "right_HandFingerTwoKnuckleOneJoint"],          # spread
            ["right_HandFingerOneKnuckleTwoJoint", "right_HandFingerOneKnuckleThreeJoint"],        # f1
            ["right_HandFingerThreeKnuckleTwoJoint", "right_HandFingerThreeKnuckleThreeJoint"],    # f3
            ["right_HandFingerTwoKnuckleTwoJoint", "right_HandFingerTwoKnuckleThreeJoint"],        # f2
            ]
            coupled_joint_names_for_fingers = ["right_HandFingerOneKnuckleThreeJoint", "right_HandFingerTwoKnuckleThreeJoint", "right_HandFingerThreeKnuckleThreeJoint"]

            actuated_joints_for_DOF = [
            ["right_HandFingerOneKnuckleOneJoint", "right_HandFingerTwoKnuckleOneJoint"],  # spread
            ["right_HandFingerOneKnuckleTwoJoint"],                                        # f1
            ["right_HandFingerThreeKnuckleTwoJoint"],                                      # f3
            ["right_HandFingerTwoKnuckleTwoJoint"]]                                        # f2

            ignored_links = ["world", "world_link"]

            self.run_ode_simulation = False
            self.insert6DofGlobalMarker(self.T_W_O)

            #
            # calculation of the configuration of the gripper for the given grasp using Openrave
            #
            self.basemanip = interfaces.BaseManipulation(self.openrave_robot)
            self.grasper = interfaces.Grasper(self.openrave_robot,friction=1.0 )

            while not rospy.is_shutdown() and not self.run_ode_simulation:
                # set the pose of the object to be grasped
                self.updatePose("object", self.T_W_O)

                # simulate the grasp
                contacts_W,finalconfig,mindist,volume = self.runGrasp(grasp_direction, grasp_initial_configuration)    # spread, f1, f3, f2
                # set the hand configuration for the grasp
                self.openrave_robot.SetDOFValues(finalconfig[0])
                # read the position of all joints
                grasp_config = {}
                for jn in joint_map:
                    grasp_config[jn] = self.openrave_robot.GetJoint(jn).GetValue(0)
                # read the position of all links
                grasp_links_poses = {}
                for link in self.openrave_robot.GetLinks():
                    grasp_links_poses[link.GetName()] = self.OpenraveToKDL(link.GetTransform())

                #
                # visualize the grasp in ROS
                #
                old_m_id = m_id
                m_id = 0
                # publish the mesh of the object
                m_id = self.pub_marker.publishConstantMeshMarker("package://barrett_hand_defs/meshes/objects/klucz_gerda_binary.stl", m_id, r=1, g=0, b=0, scale=1.0, frame_id='world', namespace='default', T=self.T_W_O)

                # update the gripper visualization in ros
                js = JointState()
                js.header.stamp = rospy.Time.now()
                for jn in joint_map:
                    js.name.append(joint_map[jn])
                    js.position.append(self.openrave_robot.GetJoint(jn).GetValue(0))
                self.pub_js.publish(js)

                contacts_reduced_W = self.reduceContacts(contacts_W)

                # draw contacts
                for c in contacts_W:
                    cc = PyKDL.Vector(c[0], c[1], c[2])
                    cn = PyKDL.Vector(c[3], c[4], c[5])
                    m_id = self.pub_marker.publishVectorMarker(cc, cc+cn*0.04, m_id, 1, 0, 0, frame='world', namespace='default', scale=0.003)

                if m_id < old_m_id:
                    self.pub_marker.eraseMarkers(m_id,old_m_id+1, frame_id='world')

                rospy.sleep(0.1)

            T_O_W = self.T_W_O.Inverse()
            contacts_reduced_O = []
            for contact_W in contacts_reduced_W:
                cc_W = PyKDL.Vector(contact_W[0], contact_W[1], contact_W[2])
                cn_W = PyKDL.Vector(contact_W[3], contact_W[4], contact_W[5])
                cc_O = T_O_W * cc_W
                cn_O = PyKDL.Frame(T_O_W.M) * cn_W
                contacts_reduced_O.append([cc_O[0], cc_O[1], cc_O[2], cn_O[0], cn_O[1], cn_O[2]])

            gws, contact_planes = self.generateGWS(contacts_reduced_O, 1.0)

            grasp_quality = None
            for wr in ext_wrenches:
                wr_qual = self.getQualituMeasure2(gws, wr)
                if grasp_quality == None or wr_qual < grasp_quality:
                    grasp_quality = wr_qual

            grasp_quality_classic = self.getQualituMeasure(gws)

            print "grasp_quality_classic: %s     grasp_quality: %s"%(grasp_quality_classic, grasp_quality)

            print "grasp_direction = [%s, %s, %s, %s]    # spread, f1, f3, f2"%(grasp_direction[0], grasp_direction[1], grasp_direction[2], grasp_direction[3])
            print "grasp_initial_configuration = [%s, %s, %s, %s]"%(grasp_initial_configuration[0], grasp_initial_configuration[1], grasp_initial_configuration[2], grasp_initial_configuration[3])
            print "grasp_final_configuration = %s"%(self.openrave_robot.GetDOFValues())
            rot_q = self.T_W_O.M.GetQuaternion()
            print "self.T_W_O = PyKDL.Frame(PyKDL.Rotation.Quaternion(%s, %s, %s, %s), PyKDL.Vector(%s, %s, %s))"%(rot_q[0], rot_q[1], rot_q[2], rot_q[3], self.T_W_O.p.x(), self.T_W_O.p.y(), self.T_W_O.p.z())

            self.erase6DofMarker()
            raw_input("Press ENTER to continue...")

            if False:
                # ICR computation
                surface_points = surfaceutils.sampleMeshDetailedRays(vertices, faces, 0.001)

                # disallow contact with the surface points beyond the key handle
                for p in surface_points:
                    if p.pos.x() > 0:
                        p.allowed = False

                for surf_pt in surface_points:
                    surf_pt.contact_regions = []

                print "calculating ICR..."
                print "surface points: %s"%(len(surface_points))
                print "contacts: %s"%(len(contacts_reduced_O))
                print "total planes in gws: %s"%(len(gws))
                print "planes for contacts:"
                for contact_idx in range(len(contacts_reduced_O)):
                    print "%s: %s"%(contact_idx, len(contact_planes[contact_idx]))

                min_quality = 0.004
                for surf_pt in surface_points:
                    if not surf_pt.allowed:
                        continue
                    wrs = self.contactToWrenches(surf_pt.pos, surf_pt.normal, 1.0, 6)
                    for contact_idx in range(len(contacts_reduced_O)):
                        contact_ok = True
                        for pl_idx in contact_planes[contact_idx]:
                            pl = gws[pl_idx]
                            pl_norm = math.sqrt(pl[0]*pl[0] + pl[1]*pl[1] + pl[2]*pl[2] + pl[3]*pl[3] + pl[4]*pl[4] + pl[5]*pl[5])
                            if pl_norm < 0.999999 or pl_norm > 1.000001:
                                print "ERROR: pl_norm = %s"%(pl_norm)
                                exit(0)
                            wrench_ok = False
                            for wr in wrs:
                                if pl[6] > 0:
                                    print "ERROR: origin no in gws: %s"%(pl[6])
                                    exit(0)

                                if pl[0]*wr[0] + pl[1]*wr[1] + pl[2]*wr[2] + pl[3]*wr[3] + pl[4]*wr[4] + pl[5]*wr[5] > min_quality: #+ pl[6] > 0:
                                    # one of the forces (wr) at the surface point (surf_pt) lies on the positive side of the plane (pl_idx) for the contact point (contact_idx)
                                    wrench_ok = True
                                    break
                            if not wrench_ok:
                                contact_ok = False
                                break
                        if contact_ok:
                            surf_pt.contact_regions.append(contact_idx)
#                    break

                print "done."

                points_icr = []
                for contact_idx in range(len(contacts_reduced_O)):
                    points_icr.append([])

                points_other = []
                total_points_in_icr = 0
                for surf_pt in surface_points:
                    if len(surf_pt.contact_regions) > 0:
                        total_points_in_icr += 1
                        for contact_idx in surf_pt.contact_regions:
                            points_icr[contact_idx].append(surf_pt.pos)
                    else:
                        points_other.append(surf_pt.pos)

                print "total surface points in ICR: %s"%(total_points_in_icr)
                for contact_idx in range(len(contacts_reduced_O)):
                    print "contact %s   points in ICR: %s"%(contact_idx, len(points_icr[contact_idx]))

                while not rospy.is_shutdown():
                    m_id = 0
                    # publish the mesh of the object
                    m_id = self.pub_marker.publishConstantMeshMarker("package://barrett_hand_defs/meshes/objects/klucz_gerda_binary.stl", m_id, r=1, g=0, b=0, scale=1.0, frame_id='world', namespace='default', T=self.T_W_O)

                    m_id = self.pub_marker.publishMultiPointsMarker(points_other, m_id, r=0, g=0, b=1, namespace='default', frame_id='world', m_type=Marker.CUBE, scale=Vector3(0.002, 0.002, 0.002), T=self.T_W_O)
                    for contact_idx in range(len(contacts_reduced_O)):
                        m_id = self.pub_marker.publishMultiPointsMarker(points_icr[contact_idx], m_id, r=0, g=1, b=0, namespace='contact_'+str(contact_idx), frame_id='world', m_type=Marker.CUBE, scale=Vector3(0.002, 0.002, 0.002), T=self.T_W_O)
                        c = contacts_reduced_W[contact_idx]
                        cc = PyKDL.Vector(c[0], c[1], c[2])
                        cn = PyKDL.Vector(c[3], c[4], c[5])
                        m_id = self.pub_marker.publishVectorMarker(cc, cc+cn*0.04, m_id, 1, 0, 0, frame='world', namespace='contact_'+str(contact_idx), scale=0.003)

                    rospy.sleep(0.1)


            # reset the gripper in Openrave
            self.openrave_robot.SetDOFValues([0,0,0,0])

            print "obtained the gripper configuration for the grasp:"
            print finalconfig[0]

            #
            # simulation in ODE
            #

            # Create a world object
            world = ode.World()
#            world.setGravity( (0,0,-3.81) )
            world.setGravity( (0,0,0) )
            CFM = world.getCFM()
            ERP = world.getERP()
            print "CFM: %s  ERP: %s"%(CFM, ERP)
#            world.setCFM(0.001)
#            print "CFM: %s  ERP: %s"%(CFM, ERP)

            self.space = ode.Space()

            # Create a body inside the world
            body = ode.Body(world)
            M = ode.Mass()
            M.setCylinderTotal(0.02, 1, 0.005, 0.09)
            body.setMass(M)

            ode_mesh = ode.TriMeshData()
            ode_mesh.build(vertices, faces)
            geom = ode.GeomTriMesh(ode_mesh, self.space)
            geom.name = "object"
            geom.setBody(body)

            self.setOdeBodyPose(geom, self.T_W_O)

            ode_gripper_geoms = {}
            for link in self.openrave_robot.GetLinks():

                link_name = link.GetName()
                if link_name in ignored_links:
                    print "ignoring: %s"%(link_name)
                    continue
                print "adding: %s"%(link_name)

                ode_mesh_link = None
                body_link = None

                T_W_L = self.OpenraveToKDL(link.GetTransform())

                col = link.GetCollisionData()
                vertices = col.vertices
                faces = col.indices
                ode_mesh_link = ode.TriMeshData()
                ode_mesh_link.build(vertices, faces)
                ode_gripper_geoms[link_name] = ode.GeomTriMesh(ode_mesh_link, self.space)

                if True:
                    body_link = ode.Body(world)
                    M_link = ode.Mass()
                    M_link.setCylinderTotal(0.05, 1, 0.01, 0.09)
                    body_link.setMass(M_link)
                    ode_gripper_geoms[link_name].setBody(body_link)
                    ode_gripper_geoms[link_name].name = link.GetName()
                    self.setOdeBodyPose(body_link, T_W_L)

            actuated_joint_names = []
            for dof in range(4):
                for joint_name in actuated_joints_for_DOF[dof]:
                    actuated_joint_names.append(joint_name)

            ode_gripper_joints = {}
            for joint_name in joint_names:
                joint = self.openrave_robot.GetJoint(joint_name)
                link_parent = joint.GetHierarchyParentLink().GetName()
                link_child = joint.GetHierarchyChildLink().GetName()
                if link_parent in ode_gripper_geoms and link_child in ode_gripper_geoms:
#                    if joint_name in actuated_joint_names:
#                    ode_gripper_joints[joint_name] = ode.AMotor(world)
#                    ode_gripper_joints[joint_name].setNumAxes(1)
#                    ode_gripper_joints[joint_name].setAxis(0,1,axis)
#                    else:
                    ode_gripper_joints[joint_name] = ode.HingeJoint(world)
                    ode_gripper_joints[joint_name].attach(ode_gripper_geoms[link_parent].getBody(), ode_gripper_geoms[link_child].getBody())
                    axis = joint.GetAxis()
                    limits = joint.GetLimits()
                    anchor = joint.GetAnchor()
                    value = joint.GetValue(0)
#                    print joint_name
#                    print "limits: %s %s"%(limits[0], limits[1])
#                    print "axis: %s"%(axis)
#                    print "anchor: %s"%(anchor)
#                    print "value: %s"%(value)

                    ode_gripper_joints[joint_name].setAxis(-axis)
                    ode_gripper_joints[joint_name].setAnchor(anchor)

                    lim = [limits[0], limits[1]]
                    if limits[0] <= -math.pi:
#                        print "lower joint limit %s <= -PI, setting to -PI+0.01"%(limits[0])
                        lim[0] = -math.pi + 0.01
                    if limits[1] >= math.pi:
#                        print "upper joint limit %s >= PI, setting to PI-0.01"%(limits[1])
                        lim[1] = math.pi - 0.01
                    ode_gripper_joints[joint_name].setParam(ode.ParamLoStop, lim[0])
                    ode_gripper_joints[joint_name].setParam(ode.ParamHiStop, lim[1])
                    ode_gripper_joints[joint_name].setParam(ode.ParamFudgeFactor, 0.5)

            ode_fixed_joint = ode.FixedJoint(world)
            ode_fixed_joint.attach(None, ode_gripper_geoms["right_HandPalmLink"].getBody())
            ode_fixed_joint.setFixed()

            #
            # set the poses of all links as for the grasp
            #
            for link_name in grasp_links_poses:
                if link_name in ignored_links:
                    continue
                ode_body = ode_gripper_geoms[link_name].getBody()
                T_W_L = grasp_links_poses[link_name]
                self.setOdeBodyPose(ode_body, T_W_L)

            fixed_joint_names = []
            fixed_joint_names += coupled_joint_names_for_fingers
            for dof in range(4):
                if grasp_direction[dof] == 0.0:
                    for joint_name in fixed_joints_names_for_fixed_DOF[dof]:
                        if not joint_name in fixed_joint_names:
                            fixed_joint_names.append(joint_name)

            #
            # change all coupled joints to fixed joints
            #
            fixed_joints = {}
            for joint_name in fixed_joint_names:
                # save the bodies attached
                body0 = ode_gripper_joints[joint_name].getBody(0)
                body1 = ode_gripper_joints[joint_name].getBody(1)
                # save the joint angle
                angle = ode_gripper_joints[joint_name].getAngle()
                # detach the joint
                ode_gripper_joints[joint_name].attach(None, None)
                del ode_gripper_joints[joint_name]
                fixed_joints[joint_name] = [ode.FixedJoint(world), angle]
                fixed_joints[joint_name][0].attach(body0, body1)
                fixed_joints[joint_name][0].setFixed()

            # change all actuated joints to motor joints
#            actuated_joint_names = []
#            for dof in range(4):
#                for joint_name in actuated_joints_for_DOF[dof]:
#                    actuated_joint_names.append(joint_name)
#            for joint_name in actuated_joint_names:


            # A joint group for the contact joints that are generated whenever
            # two bodies collide
            contactgroup = ode.JointGroup()

            print "ode_gripper_geoms:"
            print ode_gripper_geoms

            initial_T_W_O = self.T_W_O
            # Do the simulation...
            dt = 0.001
            total_time = 0.0
            failure = False
            while total_time < 5.0 and not rospy.is_shutdown():
                #
                # ODE simulation
                #

                for dof in range(4):
                    for joint_name in actuated_joints_for_DOF[dof]:
                        if joint_name in ode_gripper_joints:
                            ode_gripper_joints[joint_name].addTorque(1*grasp_direction[dof])

                self.grasp_contacts = []
                self.space.collide((world,contactgroup), self.near_callback)
                world.step(dt)
                total_time += dt
                contactgroup.empty()

                #
                # ROS interface
                #

                old_m_id = m_id
                m_id = 0
                # publish frames from ODE
                if False:
                    for link_name in ode_gripper_geoms:
                        link_body = ode_gripper_geoms[link_name].getBody()
                        if link_body == None:
                            link_body = ode_gripper_geoms[link_name]
                        T_W_Lsim = self.getOdeBodyPose(link_body)
                        m_id = self.pub_marker.publishFrameMarker(T_W_Lsim, m_id, scale=0.05, frame='world', namespace='default')

                # publish the mesh of the object
                T_W_Osim = self.getOdeBodyPose(body)
                m_id = self.pub_marker.publishConstantMeshMarker("package://barrett_hand_defs/meshes/objects/klucz_gerda_binary.stl", m_id, r=1, g=0, b=0, scale=1.0, frame_id='world', namespace='default', T=T_W_Osim)

                # update the gripper visualization in ros
                js = JointState()
                js.header.stamp = rospy.Time.now()
                for jn in joint_map:
                    ros_joint_name = joint_map[jn]
                    js.name.append(ros_joint_name)
                    if jn in ode_gripper_joints:
                        js.position.append(ode_gripper_joints[jn].getAngle())
                    elif jn in fixed_joints:
                        js.position.append(fixed_joints[jn][1])
                    else:
                        js.position.append(0)
                self.pub_js.publish(js)

                # draw contacts
                for c in self.grasp_contacts:
                    cc = PyKDL.Vector(c[0], c[1], c[2])
                    cn = PyKDL.Vector(c[3], c[4], c[5])
                    m_id = self.pub_marker.publishVectorMarker(cc, cc+cn*0.04, m_id, 1, 0, 0, frame='world', namespace='default', scale=0.003)

                if m_id < old_m_id:
                    self.pub_marker.eraseMarkers(m_id,old_m_id+1, frame_id='world')

                diff_T_W_O = PyKDL.diff(initial_T_W_O, T_W_Osim)
                if diff_T_W_O.vel.Norm() > 0.02 or diff_T_W_O.rot.Norm() > 30.0/180.0*math.pi:
                    print "the object moved"
                    print diff_T_W_O
                    failure = True
                    break
#                rospy.sleep(0.01)

            if not failure:
#                gws = self.generateGWS(self.grasp_contacts)
                T_O_Wsim = T_W_Osim.Inverse()
                TR_O_Wsim = PyKDL.Frame(T_O_Wsim.M)
                contacts = []
                for c in self.grasp_contacts:
                    cc_W = PyKDL.Vector(c[0], c[1], c[2])
                    cn_W = PyKDL.Vector(c[3], c[4], c[5])
                    cc_O = T_O_Wsim * cc_W
                    cn_O = TR_O_Wsim * cn_W
                    contacts.append([cc_O[0], cc_O[1], cc_O[2], cn_O[0], cn_O[1], cn_O[2]])
                gws, contact_planes = self.generateGWS(contacts, 1.0)

                grasp_quality = None
                for wr in ext_wrenches:
                    wr_qual = self.getQualituMeasure2(gws, wr)
                    if grasp_quality == None or wr_qual < grasp_quality:
                        grasp_quality = wr_qual

                grasp_quality_classic = self.getQualituMeasure(gws)

                print "grasp_quality_classic: %s     grasp_quality: %s"%(grasp_quality_classic, grasp_quality)

            exit(0)


if __name__ == '__main__':

    rospy.init_node('grasp_leanring')

    pub_marker = velmautils.MarkerPublisher()
    task = GraspingTask(pub_marker)
    rospy.sleep(1)

    task.spin()


