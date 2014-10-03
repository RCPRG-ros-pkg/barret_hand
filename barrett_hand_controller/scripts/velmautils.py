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
from cartesian_trajectory_msgs.msg import *
from visualization_msgs.msg import *

import tf
from tf import *
from tf.transformations import * 
import tf_conversions.posemath as pm
from tf2_msgs.msg import *

import random
import PyKDL
import math
import numpy as np
import copy
from scipy import optimize

from urdf_parser_py.urdf import URDF
from pykdl_utils.kdl_parser import kdl_tree_from_urdf_model

import dijkstra

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
        return i+1

    def publishMultiPointsMarker(self, pt, base_id, r=1, g=0, b=0, namespace='default', frame_id='torso_base', m_type=Marker.CUBE, scale=Vector3(0.002, 0.002, 0.002), T=None):
        m = MarkerArray()
        ret_id = copy.copy(base_id)
        for i in range(0, len(pt)):
            marker = Marker()
            marker.header.frame_id = frame_id
            marker.header.stamp = rospy.Time.now()
            marker.ns = namespace
            marker.id = ret_id
            ret_id += 1
            marker.type = m_type
            marker.action = 0
            if T != None:
                point = T*pt[i]
                marker.pose = Pose( Point(point.x(),point.y(),point.z()), Quaternion(0,0,0,1) )
            else:
                marker.pose = Pose( Point(pt[i].x(),pt[i].y(),pt[i].z()), Quaternion(0,0,0,1) )
            marker.scale = scale
            marker.color = ColorRGBA(r,g,b,0.5)
            m.markers.append(marker)
        self.pub_marker.publish(m)
        return ret_id

    def publishVectorMarker(self, v1, v2, i, r, g, b, frame='torso_base', namespace='default', scale=0.001):
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
        marker.scale = Vector3(scale, 2.0*scale, 0)
        marker.color = ColorRGBA(r,g,b,0.5)
        m.markers.append(marker)
        self.pub_marker.publish(m)
        return i+1

    def publishFrameMarker(self, T, base_id, scale=0.1, frame='torso_base', namespace='default'):
        self.publishVectorMarker(T*PyKDL.Vector(), T*PyKDL.Vector(scale,0,0), base_id, 1, 0, 0, frame, namespace)
        self.publishVectorMarker(T*PyKDL.Vector(), T*PyKDL.Vector(0,scale,0), base_id+1, 0, 1, 0, frame, namespace)
        self.publishVectorMarker(T*PyKDL.Vector(), T*PyKDL.Vector(0,0,scale), base_id+2, 0, 0, 1, frame, namespace)
        return base_id+3

def getAngle(v1, v2):
    return math.atan2((v1*v2).Norm(), PyKDL.dot(v1,v2))

def generateNormalsSphere(angle):
    if angle <= 0:
        return None
    v_approach = []
    i = 0
    steps_alpha = int(math.pi/angle)
    if steps_alpha < 2:
        steps_alpha = 2
    for alpha in np.linspace(-90.0/180.0*math.pi, 90.0/180.0*math.pi, steps_alpha):
        max_steps_beta = (360.0/180.0*math.pi)/angle
        steps = int(math.cos(alpha)*max_steps_beta)
        if steps < 1:
            steps = 1
        beta_d = 360.0/180.0*math.pi/steps
        for beta in np.arange(0.0, 360.0/180.0*math.pi, beta_d):
            pt = PyKDL.Vector(math.cos(alpha)*math.cos(beta), math.cos(alpha)*math.sin(beta), math.sin(alpha))
            v_approach.append(pt)
    return v_approach

def generateFramesForNormals(angle, normals):
    steps = int((360.0/180.0*math.pi)/angle)
    if steps < 2:
        steps = 2
    angle_d = 360.0/180.0*math.pi/steps
    frames = []
    for z in normals:
        if PyKDL.dot(z, PyKDL.Vector(0,0,1)) > 0.9:
            y = PyKDL.Vector(1,0,0)
        else:
            y = PyKDL.Vector(0,0,1)
        x = y * z
        y = z * x
        for angle in np.arange(0.0, 359.9/180.0*math.pi, angle_d):
            frames.append(PyKDL.Frame(PyKDL.Rotation(x,y,z)) * PyKDL.Frame(PyKDL.Rotation.RotZ(angle)))
            print angle/math.pi*180.0

    return frames

def pointInTriangle(A, B, C, P):
    # Compute vectors        
    v0 = [C[0] - A[0], C[1] - A[1]]
    v1 = [B[0] - A[0], B[1] - A[1]]
    v2 = [P[0] - A[0], P[1] - A[1]]

    # Compute dot products
    dot00 = v0[0]*v0[0] + v0[1]*v0[1]
    dot01 = v0[0]*v1[0] + v0[1]*v1[1]
    dot02 = v0[0]*v2[0] + v0[1]*v2[1]
    dot11 = v1[0]*v1[0] + v1[1]*v1[1]
    dot12 = v1[0]*v2[0] + v1[1]*v2[1]

    # Compute barycentric coordinates
    invDenom = 1.0 / (dot00 * dot11 - dot01 * dot01)
    u = (dot11 * dot02 - dot01 * dot12) * invDenom
    v = (dot00 * dot12 - dot01 * dot02) * invDenom

    # Check if point is in triangle
    return (u >= 0) and (v >= 0) and (u + v < 1)

def sampleMesh(vertices, indices, sample_dist, pt_list, radius):
        points = []
        for s2 in pt_list:
            for face in indices:
                A = vertices[face[0]]
                B = vertices[face[1]]
                C = vertices[face[2]]
                pt_a = PyKDL.Vector(A[0],A[1],A[2])
                pt_b = PyKDL.Vector(B[0],B[1],B[2])
                pt_c = PyKDL.Vector(C[0],C[1],C[2])
                v0 = pt_b - pt_a
                v1 = pt_c - pt_a
                # calculate face normal
                normal = v0 * v1
                normal.Normalize()
                # calculate distance between the sphere center and the face
                s_dist = PyKDL.dot(normal, s2) - PyKDL.dot(normal, pt_a)
                # if the distance is greater than radius, ignore the face
                if abs(s_dist) > radius:
                    continue
                # calculate the projection of the sphere center to the face
                s_on = s2 - s_dist * normal
                # calculate the radius of circle being common part of sphere and face
                radius2_square = radius * radius - s_dist * s_dist
                if radius2_square < 0.0:   # in case of numerical error
                    radius2_square = 0.0
                radius2 = math.sqrt(radius2_square)
                # TODO: check only the face's area of interest
                n0 = v0.Norm()
                steps0 = int(n0/sample_dist)
                if steps0 < 1:
                    steps0 = 1
                step_len0 = n0/steps0
                n1 = v1.Norm()
                angle = getAngle(v0,v1)
                h = n1*math.sin(angle)
                steps1 = int(h/sample_dist)
                if steps1 < 1:
                    steps1 = 1
                step_len1 = h/steps1
                x0 = step_len0/2.0
                while x0 < n0:
                    x1 = step_len1/2.0
                    while x1 < h*(1.0-x0/n0):
                        point = pt_a + v0*(x0/n0) + v1*(x1/h)
                        in_range = False
                        for s2 in pt_list:
                            if (point-s2).Norm() < radius:
                                in_range = True
                                break
                        if in_range:
                            points.append(point)
                        x1 += step_len1
                    x0 += step_len0
        if len(pt_list) == 1:
            return points
        min_dists = []
        min_dists_p_index = []
        for s in pt_list:
            min_dists.append(1000000.0)
            min_dists_p_index.append(None)
        i = 0
        for s in pt_list:
            p_index = 0
            for p in points:
                d = (s-p).Norm()
                if d < min_dists[i]:
                    min_dists[i] = d
                    min_dists_p_index[i] = p_index
                p_index += 1
            i += 1
        first_contact_index = None
        for i in range(0, len(pt_list)):
            if min_dists[i] < sample_dist*2.0:
                first_contact_index = i
                break
        if first_contact_index == None:
            print "first_contact_index == None"
            return points
        init_pt = points[min_dists_p_index[first_contact_index]]
        points_ret = []
        list_to_check = []
        list_check_from = []
        for i in range(0, len(points)):
            if (init_pt-points[i]).Norm() > radius:
                continue
            if i == min_dists_p_index[first_contact_index]:
                list_check_from.append(points[i])
            else:
                list_to_check.append(points[i])
        points_ret = []
        added_point = True
        iteration = 0
        while added_point:
            added_point = False
            list_close = []
            list_far = []
            for p in list_to_check:
                added_p = False
                for check_from in list_check_from:
                    if (check_from-p).Norm() < sample_dist*2.0:
                        added_point = True
                        added_p = True
                        list_close.append(p)
                        break
                if not added_p:
                    list_far.append(p)
            points_ret += list_check_from
            list_to_check = copy.deepcopy(list_far)
            list_check_from = copy.deepcopy(list_close)
            iteration += 1
        return points_ret


def sampleMesh_old(vertices, indices, sample_dist, pt_list, radius):
        points = []
        for face in indices:
            A = vertices[face[0]]
            B = vertices[face[1]]
            C = vertices[face[2]]
            pt_a = PyKDL.Vector(A[0],A[1],A[2])
            pt_b = PyKDL.Vector(B[0],B[1],B[2])
            pt_c = PyKDL.Vector(C[0],C[1],C[2])
            v0 = pt_b - pt_a
            n0 = v0.Norm()
            steps0 = int(n0/sample_dist)
            if steps0 < 1:
                steps0 = 1
            step_len0 = n0/steps0
            v1 = pt_c - pt_a
            n1 = v1.Norm()
            angle = getAngle(v0,v1)
            h = n1*math.sin(angle)
            steps1 = int(h/sample_dist)
            if steps1 < 1:
                steps1 = 1
            step_len1 = h/steps1
            x0 = step_len0/2.0
            while x0 < n0:
                x1 = step_len1/2.0
                while x1 < h*(1.0-x0/n0):
                    point = pt_a + v0*(x0/n0) + v1*(x1/h)
                    in_range = False
                    for s2 in pt_list:
                        if (point-s2).Norm() < radius:
                            in_range = True
                            break
                    if in_range:
                        points.append(point)
                    x1 += step_len1
                x0 += step_len0
        if len(pt_list) == 1:
            return points
        min_dists = []
        min_dists_p_index = []
        for s in pt_list:
            min_dists.append(1000000.0)
            min_dists_p_index.append(None)
        i = 0
        for s in pt_list:
            p_index = 0
            for p in points:
                d = (s-p).Norm()
                if d < min_dists[i]:
                    min_dists[i] = d
                    min_dists_p_index[i] = p_index
                p_index += 1
            i += 1
        first_contact_index = None
        for i in range(0, len(pt_list)):
            if min_dists[i] < sample_dist*2.0:
                first_contact_index = i
                break
        if first_contact_index == None:
            print "first_contact_index == None"
            return points
        init_pt = points[min_dists_p_index[first_contact_index]]
        points_ret = []
        list_to_check = []
        list_check_from = []
        for i in range(0, len(points)):
            if (init_pt-points[i]).Norm() > radius:
                continue
            if i == min_dists_p_index[first_contact_index]:
                list_check_from.append(points[i])
            else:
                list_to_check.append(points[i])
        points_ret = []
        added_point = True
        iteration = 0
        while added_point:
            added_point = False
            list_close = []
            list_far = []
            for p in list_to_check:
                added_p = False
                for check_from in list_check_from:
                    if (check_from-p).Norm() < sample_dist*2.0:
                        added_point = True
                        added_p = True
                        list_close.append(p)
                        break
                if not added_p:
                    list_far.append(p)
            points_ret += list_check_from
            list_to_check = copy.deepcopy(list_far)
            list_check_from = copy.deepcopy(list_close)
            iteration += 1
        return points_ret

def estPlane(points_in):
    mean_pt = PyKDL.Vector()
    for p in points_in:
        mean_pt += p
    mean_pt *= (1.0/len(points_in))

    points = []
    for p in points_in:
        points.append(p-mean_pt)

    def calc_R(xa, ya):
        ret = []
        """ calculate the minimum distance of each contact point from jar surface pt """
        n = PyKDL.Frame(PyKDL.Rotation.RotX(xa)) * PyKDL.Frame(PyKDL.Rotation.RotY(ya)) * PyKDL.Vector(0,0,1)
        for p in points:
            ret.append(PyKDL.dot(n,p))
        return numpy.array(ret)
        
    def f_2(c):
        """ calculate the algebraic distance between each contact point and jar surface pt """
        Di = calc_R(*c)
        return Di

    angles_estimate = 0.0, 0.0
    angles_2, ier = optimize.leastsq(f_2, angles_estimate, maxfev = 1000)
    n = PyKDL.Frame(PyKDL.Rotation.RotX(angles_2[0])) * PyKDL.Frame(PyKDL.Rotation.RotY(angles_2[1])) * PyKDL.Vector(0,0,1)

    nz = n
    if math.fabs(n.x()) < 0.9:
        nx = PyKDL.Vector(1,0,0)
    else:
        nx = PyKDL.Vector(0,1,0)

    ny = nz*nx
    nx = ny*nz
    nx.Normalize()
    ny.Normalize()
    nz.Normalize()

    return PyKDL.Frame(PyKDL.Rotation(nx,ny,nz), mean_pt)

def sampleMeshUnitTest(vertices, indices, pub_marker):
    points = sampleMesh(vertices, indices, 0.002, [PyKDL.Vector(0.00,0,0.00)], 0.04)
    print len(points)
    m_id = 0
    m_id = pub_marker.publishMultiPointsMarker(points, m_id, r=1, g=0, b=0, namespace='default', frame_id='torso_base', m_type=Marker.CUBE, scale=Vector3(0.001, 0.001, 0.001))
    raw_input("Press Enter to continue...")
    rospy.sleep(5.0)
    pt_list = []
    for i in range(0, 20):
        pt_list.append(PyKDL.Vector((1.0*i/20.0)*0.1-0.05, 0, 0))
    points = sampleMesh(vertices, indices, 0.002, pt_list, 0.01)
    print len(points)
    m_id = 0
    m_id = pub_marker.publishMultiPointsMarker(points, m_id, r=1, g=0, b=0, namespace='default', frame_id='torso_base', m_type=Marker.CUBE, scale=Vector3(0.001, 0.001, 0.001))
    rospy.sleep(1.0)
    fr = estPlane(points)
    m_id = pub_marker.publishFrameMarker(fr, m_id)
    rospy.sleep(1.0)

def meanOrientation(T):
    R = []
    for t in T:
        R.append( copy.deepcopy( PyKDL.Frame(t.M) ) )

    def calc_R(rx, ry, rz):
        R_mean = PyKDL.Frame(PyKDL.Rotation.EulerZYX(rx, ry, rz))
        diff = []
        for r in R:
            diff.append(PyKDL.diff( R_mean, r ))
        ret = [math.fabs(d.rot.x()) for d in diff] + [math.fabs(d.rot.y()) for d in diff] + [math.fabs(d.rot.z()) for d in diff]
        return ret
    def f_2(c):
        """ calculate the algebraic distance between each contact point and jar surface pt """
        Di = calc_R(*c)
        return Di
    angle_estimate = R[0].M.GetEulerZYX()
    angle_2, ier = optimize.leastsq(f_2, angle_estimate, maxfev = 10000)
    score = calc_R(angle_2[0],angle_2[1],angle_2[2])
    score_v = 0.0
    for s in score:
        score_v += s*s
    return [score_v, PyKDL.Frame(PyKDL.Rotation.EulerZYX(angle_2[0],angle_2[1],angle_2[2]))]

# determine if a point is inside a given polygon or not
# Polygon is a list of (x,y) pairs.
def point_inside_polygon(x,y,poly):
    n = len(poly)
    inside =False
    p1x,p1y = poly[0]
    for i in range(n+1):
        p2x,p2y = poly[i % n]
        if y > min(p1y,p2y):
            if y <= max(p1y,p2y):
                if x <= max(p1x,p2x):
                    if p1y != p2y:
                        xinters = (y-p1y)*(p2x-p1x)/(p2y-p1y)+p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x,p1y = p2x,p2y
    return inside

class WristCollisionAvoidance:

    def getSectorWithMargin(self, sector):
        return [self.q5_q6_restricted_area[sector][0]+self.margin, self.q5_q6_restricted_area[sector][1]-self.margin, self.q5_q6_restricted_area[sector][2]+self.margin, self.q5_q6_restricted_area[sector][3]-self.margin]

    def __init__(self, prefix, q5_positive, margin):
        self.margin = margin
        if prefix == "right":
            if q5_positive != None:
                if q5_positive:
                    self.q5_q6_restricted_area = [
                    [0.0,1.92521262169,-2.89507389069,-1.38213706017],
                    [0.0,0.435783565044,-1.52231526375,2.22040915489],
                    [0.0,2.07619023323,0.932657182217,2.86872577667],
                    [0.0, 0.494, -1.885, -1.157],
                    [0.0, 0.750, 0.457, 2.564],
                    ]
                else:
                    self.q5_q6_restricted_area = [
                    [-0.428265035152,0.0,-2.89507389069,-1.38213706017],
                    [-2.11473441124,0.0,-1.52231526375,2.22040915489],
                    [-0.819031119347,0.0,0.932657182217,2.86872577667],
                    [-0.609, 0.0, -1.885, -1.157],
                    [-1.061, 0.0, 0.457, 2.564],
                    ]
            else:
                self.q5_q6_restricted_area = [
                [-0.428265035152,1.92521262169,-2.89507389069,-1.38213706017],
                [-2.11473441124,0.435783565044,-1.52231526375,2.22040915489],
                [-0.819031119347,2.07619023323,0.932657182217,2.86872577667],
                [-0.609, 0.494, -1.885, -1.157],
                [-1.061, 0.750, 0.457, 2.564],
                ]
            self.sectors_count = len(self.q5_q6_restricted_area)

            self.gateways = []
            for i in range(0, self.sectors_count):
                r1 = self.getSectorWithMargin(i)
                self.gateways.append({})
                for j in range(0, self.sectors_count):
                    if i == j:
                        continue
                    r2 = self.getSectorWithMargin(j)
                    r_int = [max(r1[0], r2[0]), min(r1[1], r2[1]), max(r1[2], r2[2]), min(r1[3], r2[3])]
                    # the two rectangles are intersecting
                    if r_int[1] - r_int[0] > 0 and r_int[3] - r_int[2] > 0:
                        self.gateways[-1][j] = [(r_int[0] + r_int[1]/2.0), (r_int[2] + r_int[3])/2.0]

            # create the graph based on gateways
            self.G = {}
            for i in range(0, self.sectors_count):
                for j in self.gateways[i].keys():
                    neighbours = self.G.get(i, {})
                    neighbours[j] = 1
                    self.G[i] = neighbours
                    neighbours = self.G.get(j, {})
                    neighbours[i] = 1
                    self.G[j] = neighbours

        if self.q5_q6_restricted_area == None:
            print "WristCollisionAvoidance ERROR: wrong prefix: %s"%(prefix)

    def getQ5Q6SpaceSectors(self, q5, q6):
        sectors = []
        # x1,x2,y1,y2
        for idx in range(0, self.sectors_count):
            rect = self.getSectorWithMargin(idx)
            if q5 >= rect[0] and q5 <= rect[1] and q6 >= rect[2] and q6 <= rect[3]:
                sectors.append(idx)
        return sectors

    def getClosestQ5Q6SpaceSector(self, q5, q6):
        sect = self.getQ5Q6SpaceSectors(q5, q6)
        if len(sect) > 0:
            return sect[0]
        min_dist = 1000000.0
        min_index = -1
        # x1,x2,y1,y2
        for idx in range(0, self.sectors_count):
            rect = self.getSectorWithMargin(idx)
            d5 = 1000000.0
            d6 = 1000000.0
            if q5 < rect[0]:
                d5 = rect[0] - q5
            elif q5 > rect[1]:
                d5 = q5 - rect[1]
            if q6 < rect[2]:
                d6 = rect[2] - q6
            elif q6 > rect[3]:
                d6 = q6 - rect[3]
            dist = min( d5, d6 )
            if dist < min_dist:
                min_dist = dist
                min_index = idx
        return min_index

    def forceMoveQ5Q6ToSector(self, q5, q6, sector):
        rect = self.getSectorWithMargin(sector)
        r = PyKDL.Vector((rect[1]-rect[0])/2.0, (rect[3]-rect[2])/2.0, 0.0)
        center = PyKDL.Vector((rect[0]+rect[1])/2.0, (rect[2]+rect[3])/2.0, 0.0)
        q = PyKDL.Vector(q5, q6, 0.0)
        v = q - center
        if v.x() > r.x() or v.x() < -r.x():
            f = math.fabs(r.x()/v.x())
            v.Normalize()
            v *= f
        if v.y() > r.y() or v.y() < -r.y():
            f = math.fabs(r.y()/v.y())
            v.Normalize()
            v *= f
        return [v.x() + center.x(), v.y() + center.y()]

    # returns [q5_diff q6_diff] with proper vector direction and with length of the whole path through sectors
    def moveQ5Q6ToDest(self, q5, q6, q5_d, q6_d):
        sect_d = self.getQ5Q6SpaceSectors(q5_d, q6_d)
        # if destination is outside, force it to the nearest sector
        if len(sect_d) == 0:
            closest_sect_d = self.getClosestQ5Q6SpaceSector(q5_d, q6_d)
            q5_d, q6_d = self.forceMoveQ5Q6ToSector(q5_d, q6_d, closest_sect_d)
            sect_d = self.getQ5Q6SpaceSectors(q5_d, q6_d)

        sect = self.getQ5Q6SpaceSectors(q5, q6)
        if len(sect) == 0:
            closest_sect = self.getClosestQ5Q6SpaceSector(q5, q6)
            q5, q6 = self.forceMoveQ5Q6ToSector(q5, q6, closest_sect)
            sect = self.getQ5Q6SpaceSectors(q5, q6)

        same_sector = False
        for s in sect:
            if s in sect_d:
                same_sector = True
                break
        if same_sector:
            print "same_sect"
            return [q5_d - q5, q6_d - q6]

        path_len = 1000000
        best_path = None
        for s in sect:
            for s_d in sect_d:
                path = dijkstra.shortestPath(self.G, s, s_d)
                if len(path) < path_len:
                    path_len = len(path)
                    best_path = path
        print best_path
        gateways_d = []
        for idx in range(0, len(best_path)-1):
            gateways_d.append( [self.gateways[best_path[idx]][best_path[idx+1]][0], self.gateways[best_path[idx]][best_path[idx+1]][1]] )

        length = math.sqrt((gateways_d[0][0]-q5)*(gateways_d[0][0]-q5) + (gateways_d[0][1]-q6)*(gateways_d[0][1]-q6))
        first_move_len = copy.copy(length)
        for idx in range(0, len(gateways_d)-1):
            length += math.sqrt((gateways_d[idx][0]-gateways_d[idx+1][0])*(gateways_d[idx][0]-gateways_d[idx+1][0]) + (gateways_d[idx][1]-gateways_d[idx+1][1])*(gateways_d[idx][1]-gateways_d[idx+1][1]))
        length += math.sqrt((gateways_d[-1][0]-q5_d)*(gateways_d[-1][0]-q5_d) + (gateways_d[-1][1]-q6_d)*(gateways_d[-1][1]-q6_d))

        return [length * (gateways_d[0][0] - q5) / first_move_len, length * (gateways_d[0][1] - q6) / first_move_len]

    # returns trajectory for q5 and q6 and its length
    def moveQ5Q6ToDestTraj(self, q5_i, q6_i, q5_d, q6_d, diff_max):
        sect_d = self.getQ5Q6SpaceSectors(q5_d, q6_d)
        # if destination is outside, force it to the nearest sector
        if len(sect_d) == 0:
            print "moveQ5Q6ToDestTraj: q_dest is outside space: %s"%([q5_d, q6_d])
            return None
        sect = self.getQ5Q6SpaceSectors(q5_i, q6_i)
        if len(sect) == 0:
            print "moveQ5Q6ToDestTraj: q_init is outside space: %s"%([q5_i, q6_i])
            return None

        same_sector = False
        for s in sect:
            if s in sect_d:
                same_sector = True
                break
        if same_sector:
            length = math.sqrt((q5_d - q5_i)*(q5_d - q5_i) + (q6_d - q6_i)*(q6_d - q6_i))
            steps = int(length/diff_max)
            if steps < 2:
                steps = 2
            q5_traj = np.linspace(q5_i, q5_d, steps)
            q6_traj = np.linspace(q6_i, q6_d, steps)
            traj = []
            for i in range(0, steps):
                traj.append( [q5_traj[i], q6_traj[i]] )
            return traj, length

        path_len = 1000000
        best_path = None
        for s in sect:
            for s_d in sect_d:
                path = dijkstra.shortestPath(self.G, s, s_d)
                if len(path) < path_len:
                    path_len = len(path)
                    best_path = path

        gateways_d = [[q5_i,q6_i]]
        for idx in range(0, len(best_path)-1):
            gateways_d.append( [self.gateways[best_path[idx]][best_path[idx+1]][0], self.gateways[best_path[idx]][best_path[idx+1]][1]] )
        gateways_d.append([q5_d,q6_d])

        traj = []

        total_length = 0.0
        for idx in range(0, len(gateways_d)-1):
            length = math.sqrt((gateways_d[idx][0]-gateways_d[idx+1][0])*(gateways_d[idx][0]-gateways_d[idx+1][0]) + (gateways_d[idx][1]-gateways_d[idx+1][1])*(gateways_d[idx][1]-gateways_d[idx+1][1]))
            total_length += length
            steps = int(length/diff_max)
            if steps < 2:
                steps = 2
            q5_traj = np.linspace(gateways_d[idx][0], gateways_d[idx+1][0], steps)
            q6_traj = np.linspace(gateways_d[idx][1], gateways_d[idx+1][1], steps)
            for i in range(0, steps):
                traj.append( [q5_traj[i], q6_traj[i]] )
            
        return traj, total_length

class VelmaIkSolver:
    def __init__(self):
        pass

    def initIkSolver(self):
        self.robot = None
        try:
            self.robot = URDF.from_parameter_server()
        except:
            pass

        if self.robot == None:
            print "Could not load the robot description!"
            print "Please run <roscore> and then <roslaunch velma_description upload_robot.launch>"
            return

        print "len(self.robot.links) = %s"%(len(self.robot.links))
#        for l in self.robot.links:
#            print "name: %s"%(l.name)
#            print "visual:"
#            print l.visual
#            print "collision:"
#            print l.collision.geometry
        self.tree = kdl_tree_from_urdf_model(self.robot)
        self.chain = self.tree.getChain("torso_link2", "right_HandPalmLink")

        self.q_min = PyKDL.JntArray(7)
        self.q_max = PyKDL.JntArray(7)
        self.q_limit = 0.26
        self.q_min[0] = -2.96 + self.q_limit
#        self.q_min[1] = -2.09 + self.q_limit
        self.q_min[1] = 0.1
        self.q_min[2] = -2.96 + self.q_limit
        self.q_min[3] = -2.09 + self.q_limit
#        self.q_min[3] = 0.1    # constraint on elbow
        self.q_min[4] = -2.96 + self.q_limit
        self.q_min[5] = -2.09 + self.q_limit
        self.q_min[6] = -2.96 + self.q_limit
#        self.q_max[0] = 2.96 - self.q_limit
        self.q_max[0] = 0.2    # constraint on first joint to avoid head hitting
        self.q_max[1] = 2.09 - self.q_limit
        self.q_max[2] = 2.96 - self.q_limit
#        self.q_max[2] = 0.0
        self.q_max[3] = 2.09 - self.q_limit
        self.q_max[4] = 2.96 - self.q_limit
        self.q_max[5] = 2.09 - self.q_limit
        self.q_max[6] = 2.96 - self.q_limit
        self.fk_solver = PyKDL.ChainFkSolverPos_recursive(self.chain)
        self.vel_ik_solver = PyKDL.ChainIkSolverVel_pinv(self.chain)
        self.ik_solver = PyKDL.ChainIkSolverPos_NR_JL(self.chain, self.q_min, self.q_max, self.fk_solver, self.vel_ik_solver, 100)

        self.q_min_no_sing = []
        self.q_max_no_sing = []
        self.ik_solver_no_sing = []
        self.wrist_collision_avoidance = []
#        for q1_lim in [(self.q_min[1],0.0),(0.0, self.q_max[1])]:
        if True:
            for q3_lim in [(self.q_min[3],-10.0/180.0*math.pi),(10.0/180.0*math.pi, self.q_max[3])]:
                for q5_lim in [(self.q_min[5],0.0),(0.0, self.q_max[5])]:
                    self.q_min_no_sing.append(PyKDL.JntArray(7))
                    self.q_max_no_sing.append(PyKDL.JntArray(7))
                    for i in range(0, 7):
                        self.q_min_no_sing[-1][i] = copy.copy(self.q_min[i])
                        self.q_max_no_sing[-1][i] = copy.copy(self.q_max[i])
#                    self.q_min_no_sing[-1][1] = q1_lim[0]
#                    self.q_max_no_sing[-1][1] = q1_lim[1]
                    self.q_min_no_sing[-1][3] = q3_lim[0]
                    self.q_max_no_sing[-1][3] = q3_lim[1]
                    self.q_min_no_sing[-1][5] = q5_lim[0]
                    self.q_max_no_sing[-1][5] = q5_lim[1]
                    self.ik_solver_no_sing.append(PyKDL.ChainIkSolverPos_NR_JL(self.chain, self.q_min_no_sing[-1], self.q_max_no_sing[-1], self.fk_solver, self.vel_ik_solver, 100))
                    self.wrist_collision_avoidance.append(WristCollisionAvoidance("right", q5_lim[0]+q5_lim[1] > 0, 5.0/180.0*math.pi))

        self.ik_solver = PyKDL.ChainIkSolverPos_NR_JL(self.chain, self.q_min, self.q_max, self.fk_solver, self.vel_ik_solver, 100)

    def simulateTrajectory(self, T_B_Einit, T_B_Ed, progress, q_start, T_T2_B, ik_solver=None):
        if progress < 0.0 or progress > 1.0:
            print "simulateTrajectory: bad progress value: %s"%(progress)
            return None

        if ik_solver == None:
            ik_solver = self.ik_solver

        q_end = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        q_init = PyKDL.JntArray(7)
        for i in range(0,7):
            q_init[i] = q_start[i]

        for i in range(0, 7):
            if q_init[i] > self.q_max[i]-0.02:
                q_init[i] = self.q_max[i]-0.02
            if q_init[i] < self.q_min[i]+0.02:
                q_init[i] = self.q_min[i]+0.02

        q_out = PyKDL.JntArray(7)
        T_B_E_diff = PyKDL.diff(T_B_Einit, T_B_Ed, 1.0)
        T_B_Ei = PyKDL.addDelta(T_B_Einit, T_B_E_diff, progress)
        T_T2_Ei = T_T2_B * T_B_Ei
        status = ik_solver.CartToJnt(q_init, T_T2_Ei, q_out)
        if status != 0:
            return None, None
        for i in range(0, 7):
            q_end[i] = q_out[i]
        return q_end, T_B_Ei

    def getTrajCost(self, traj_T_B_Ed, q_start, T_T2_B, allow_q5_singularity_before_end, allow_q5_singularity_on_end):
        if len(traj_T_B_Ed) < 2:
            print "getTrajCost: wrong argument"
            return 1000000.0

        q_init = copy.copy(q_start)
        for i in range(0, 7):
            if q_init[i] > self.q_max[i]-0.02:
                q_init[i] = self.q_max[i]-0.02
            if q_init[i] < self.q_min[i]+0.02:
                q_init[i] = self.q_min[i]+0.02

        q_out = PyKDL.JntArray(7)
        steps = 10
        time_set = np.linspace(1.0/steps, 1.0, steps)
        cost = 0.0
#        for T_B_Ed in traj_T_B_Ed:
        for i in range(0, len(traj_T_B_Ed)-1):

            for f in time_set:
                q_end, T_B_Ei = self.simulateTrajectory(traj_T_B_Ed[i], traj_T_B_Ed[i+1], f, q_init, T_T2_B)
                if q_end == None:
                    cost += 10000.0
                    return cost
#                T_B_Ei = PyKDL.addDelta(T_B_Eprev, T_B_E_diff, d)
#                T_T2_Ei = self.T_T2_B * T_B_Ei
#                status = self.ik_solver.CartToJnt(q_init, T_T2_Ei, q_out)
#                if status != 0:
#                    print "c"
#                    cost += 10000.0
#                    return cost
#                q5abs = math.fabs(q_out[5])
#                singularity = q5abs < self.abort_on_q5_singularity_angle + 5.0/180.0*math.pi
#                if allow_q5_singularity_before_end:
#                    pass
#                else:
#                    # punish for singularity
#                    if singularity:
#                        print "b"
#                        cost += 10000.0
#                        return cost
                for j in range(0, 7):
                    cost += (q_end[j] - q_init[j])*(q_end[j] - q_init[j])
                    q_init[j] = q_end[j]
#        if not allow_q5_singularity_on_end and singularity:
#            print "a"
#            cost += 10000.0
#            return cost

#        if q_end != None:
#            for i in range(0, 7):
#                q_end[i] = q_out[i]
        return cost

    def getAllDistinctConfigurations(self, T_B_Ed, T_T2_B):
        T_T2_Ed = T_T2_B * T_B_Ed
        ret = []
        for ik_solver_idx in range(0, len(self.ik_solver_no_sing)):
            for tries in range(0, 10):
                q_init = PyKDL.JntArray(7)
                q_out = PyKDL.JntArray(7)
                for i in range(0,7):
                    q_init[i] = random.uniform(self.q_min_no_sing[ik_solver_idx][i], self.q_max_no_sing[ik_solver_idx][i])
                status = self.ik_solver_no_sing[ik_solver_idx].CartToJnt(q_init, T_T2_Ed, q_out)
                if status == 0:
                    ret.append( [q_out[0], q_out[1], q_out[2], q_out[3], q_out[4], q_out[5], q_out[6]] )
                    break
        return ret

    def planTrajectoryInOneSubspace(self, T_B_Einit, T_B_Ed, T_W_E, q_start, T_T2_B):
        ik_solver_idx = self.getJointSubspaceIndex(q_start)
        if ik_solver_idx == None:
            print "ERROR: could not find joint subspace for q_start: %s"%(q_start)
            return None
        ik_solver = self.ik_solver_no_sing[ik_solver_idx]

        T_T2_Ed = T_T2_B * T_B_Ed
        min_cost = 1000000.0
        best_q_out = None
        for tries in range(0, 20):
            q_init = PyKDL.JntArray(7)
            q_out = PyKDL.JntArray(7)
            for i in range(0,7):
                q_init[i] = random.uniform(self.q_min_no_sing[ik_solver_idx][i], self.q_max_no_sing[ik_solver_idx][i])
            status = ik_solver.CartToJnt(q_init, T_T2_Ed, q_out)
            if len(self.wrist_collision_avoidance[ik_solver_idx].getQ5Q6SpaceSectors(q_out[5], q_out[6])) == 0:
                status = 10

            if status == 0:
                cost = 0.0
                for i in range(0,7):
                    low_joint_penalty = (6.0-i)/6.0
                    distance_penalty = (q_out[i]-q_start[i])*(q_out[i]-q_start[i])
                    dist_to_limit = min( math.fabs(q_out[i]-self.q_min_no_sing[ik_solver_idx][i]), math.fabs(q_out[i]-self.q_max_no_sing[ik_solver_idx][i]) )
                    close_limit_penalty = dist_to_limit
                    cost += low_joint_penalty * distance_penalty * close_limit_penalty
#                print "cost: %s"%(cost)
                if cost < min_cost:
                    min_cost = cost
                    best_q_out = q_out

        if min_cost > 1000.0:
            print "could not find ik solution for end pose"
            return None, None

        q_diff = []
        # get max diff
        max_diff = -10.0
        max_idx = -1
        for i in range(0,7):
            diff = best_q_out[i]-q_start[i]
            q_diff.append(diff)
            if math.fabs(diff) > max_diff:
                max_diff = math.fabs(diff)
                max_idx = i

        print "q_start: %s"%(q_start)
        print "q_out: %s"%(best_q_out)

        print "q_diff: %s"%(q_diff)

        return max_idx, best_q_out[max_idx]-q_start[max_idx]

    def isLinearTrajectoryPossibleInOneSubspace(self, T_B_Einit, T_B_Ed, q_start, T_T2_B):
        ik_solver_idx = self.getJointSubspaceIndex(q_start)
        if ik_solver_idx == None:
            print "ERROR: could not find joint subspace for q_start: %s"%(q_start)
            return None
        ik_solver = self.ik_solver_no_sing[ik_solver_idx]

        diff = PyKDL.diff(T_B_Einit, T_B_Ed, 1.0)

        if diff.rot.Norm() > 30.0/180.0*math.pi or diff.vel.Norm() > 0.1:
            return None, None

        success = True
        T_T2_Ed = T_T2_B * T_B_Ed
        for progress in np.linspace(0.0, 1.0, 25):
            q_end, T_B_Ei = self.simulateTrajectory(T_B_Einit, T_B_Ed, progress, q_start, T_T2_B, ik_solver=ik_solver)
            if q_end == None:
                success = False
                break
            if len(self.wrist_collision_avoidance[ik_solver_idx].getQ5Q6SpaceSectors(q_end[5], q_end[6])) == 0:
                success = False
                break
        return success, q_end

    def isTrajectoryPossibleInOneSubspace(self, T_B_Ed, q_start, T_T2_B):
        ik_solver_idx = self.getJointSubspaceIndex(q_start)
        if ik_solver_idx == None:
            print "ERROR: could not find joint subspace for q_start: %s"%(q_start)
            return None
        ik_solver = self.ik_solver_no_sing[ik_solver_idx]

        q5q6_problem = 0
        ik_problem = 0
        T_T2_Ed = T_T2_B * T_B_Ed
        for tries in range(0, 10):
            q_init = PyKDL.JntArray(7)
            q_out = PyKDL.JntArray(7)
            for i in range(0,7):
                q_init[i] = random.uniform(self.q_min_no_sing[ik_solver_idx][i]+0.1, self.q_max_no_sing[ik_solver_idx][i]-0.1)
            status = ik_solver.CartToJnt(q_init, T_T2_Ed, q_out)
            if status != 0:
                ik_problem += 1
            if len(self.wrist_collision_avoidance[ik_solver_idx].getQ5Q6SpaceSectors(q_out[5], q_out[6])) == 0:
                status = 10
                q5q6_problem += 1
            for i in range(0,7):
                if q_out[i] < self.q_min_no_sing[ik_solver_idx][i]+0.1 or q_out[i] > self.q_max_no_sing[ik_solver_idx][i]-0.1:
                    status = 20
                    break

            if status == 0:
                return [q_out[0], q_out[1], q_out[2], q_out[3], q_out[4], q_out[5], q_out[6]]
                break
#        print "isTrajectoryPossibleInOneSubspace: ik_problem: %s   q5q6_problem: %s"%(ik_problem, q5q6_problem)
        return None

    def incrementTrajectoryInOneSubspace(self, T_B_Einit, T_B_Ed, T_W_E, q_start, T_T2_B, q_end=None):
        ik_solver_idx = self.getJointSubspaceIndex(q_start)
        if ik_solver_idx == None:
            print "ERROR: could not find joint subspace for q_start: %s"%(q_start)
            return None
        ik_solver = self.ik_solver_no_sing[ik_solver_idx]

        if q_end != None:
            q_end_ok = True
            for i in range(0,7):
                if q_end[i] < self.q_min_no_sing[ik_solver_idx][i] or q_end[i] > self.q_max_no_sing[ik_solver_idx][i]:
                    q_end_ok = False
                    break
            if not q_end_ok:
                print "q_start and q_end are in diffrent subspaces"
                return None
            best_q_out = q_end
        else:
            q5q6_problem = 0
            ik_problem = 0
            T_T2_Ed = T_T2_B * T_B_Ed
            min_cost = 1000000.0
            best_q_out = None
            for tries in range(0, 20):
                q_init = PyKDL.JntArray(7)
                q_out = PyKDL.JntArray(7)
                for i in range(0,7):
                    q_init[i] = random.uniform(self.q_min_no_sing[ik_solver_idx][i], self.q_max_no_sing[ik_solver_idx][i])
                status = ik_solver.CartToJnt(q_init, T_T2_Ed, q_out)
                if status != 0:
                    ik_problem += 1
                elif len(self.wrist_collision_avoidance[ik_solver_idx].getQ5Q6SpaceSectors(q_out[5], q_out[6])) == 0:
                    q5q6_problem += 1
                    status = 10

                if status == 0:
                    cost = 0.0
                    for i in range(0,7):
                        low_joint_penalty = (6.0-i)/6.0
                        distance_penalty = (q_out[i]-q_start[i])*(q_out[i]-q_start[i])
                        dist_to_limit = min( math.fabs(q_out[i]-self.q_min_no_sing[ik_solver_idx][i]), math.fabs(q_out[i]-self.q_max_no_sing[ik_solver_idx][i]) )
                        close_limit_penalty = dist_to_limit
                        cost += low_joint_penalty * distance_penalty * close_limit_penalty
                    if cost < min_cost:
                        min_cost = cost
                        best_q_out = q_out

            if min_cost > 1000.0:
                print "incrementTrajectoryInOneSubspace: could not find ik solution for end pose: ik_problem: %s, q5q6_problem: %s"%(ik_problem, q5q6_problem)
                print "   q_start: %s"%(q_start)
                print "   q_limit: %s"%(q_start)
                return None

        q_diff = []
        for i in range(0,7):
            diff = best_q_out[i]-q_start[i]
            q_diff.append(diff)
        q_diff[5], q_diff[6] = self.wrist_collision_avoidance[ik_solver_idx].moveQ5Q6ToDest(q_start[5], q_start[6], best_q_out[5], best_q_out[6])

        # get max diff
        max_diff = -10.0
        for diff in q_diff:
            if math.fabs(diff) > max_diff:
                max_diff = math.fabs(diff)

        # limit the maximum speed
        q_vel_limit = 30.0/180.0*math.pi
        time_d = 0.1
        vel_factor = q_vel_limit/max_diff

        # calculate the next end effector pose
        q_dest = PyKDL.JntArray(7)
        for i in range(0,7):
            q_dest[i] = q_start[i] + q_diff[i] * vel_factor * time_d

        q_dest_norm = []
        for i in range(0, 7):
            q_dest_norm.append((q_dest[i]-self.q_min_no_sing[ik_solver_idx][i])/(self.q_max_no_sing[ik_solver_idx][i]-self.q_min_no_sing[ik_solver_idx][i]))

        q_end_norm = []
        for i in range(0, 7):
            q_end_norm.append((q_end[i]-self.q_min_no_sing[ik_solver_idx][i])/(self.q_max_no_sing[ik_solver_idx][i]-self.q_min_no_sing[ik_solver_idx][i]))

        print "q_diff"
        print q_diff

        T_T2_Ed = PyKDL.Frame()
        self.fk_solver.JntToCart(q_dest, T_T2_Ed)
        T_B_Ed = T_T2_B.Inverse() * T_T2_Ed

        return T_B_Ed

    def generateJointTrajectoryInOneSubspace(self, q_start, q_end, q_vel_limit):
        ik_solver_idx = self.getJointSubspaceIndex(q_start)
        if ik_solver_idx == None:
            print "ERROR: could not find joint subspace for q_start: %s"%(q_start)
            return None
        ik_solver = self.q_min_no_sing[ik_solver_idx]

        if ik_solver_idx != self.getJointSubspaceIndex(q_end):
            print "ERROR: q_start and q_end are in diffrent subspaces"
            return None

        traj_q5q6, len_q5q6 = self.wrist_collision_avoidance[ik_solver_idx].moveQ5Q6ToDestTraj(q_start[5], q_start[6], q_end[5], q_end[6], 0.1)
 
        q_diff = []
        # get max diff
        for i in range(0,7):
            diff = q_end[i]-q_start[i]
            q_diff.append(diff)
        q_diff[5] = len_q5q6
        q_diff[6] = len_q5q6
        max_diff = -10.0
        for diff in q_diff:
            if math.fabs(diff) > max_diff:
                max_diff = math.fabs(diff)

        # limit the maximum speed
        time_d = 0.01
        time = max_diff/q_vel_limit

        steps = int(time/time_d)
        if steps < 2:
            steps = 2

        q_traj = []
        for i in range(0,5):
            q_traj.append(np.linspace(q_start[i], q_end[i], steps))

        traj_q5q6, len_q5q6 = self.wrist_collision_avoidance[ik_solver_idx].moveQ5Q6ToDestTraj(q_start[5], q_start[6], q_end[5], q_end[6], len_q5q6/steps)

        traj = []
        for idx in range(0, max(steps, len(traj_q5q6))):
            if idx < steps and idx < len(traj_q5q6):
                traj.append( [q_traj[0][idx], q_traj[1][idx], q_traj[2][idx], q_traj[3][idx], q_traj[4][idx], traj_q5q6[idx][0], traj_q5q6[idx][1] ] )
            elif idx < steps:
                traj.append( [q_traj[0][idx], q_traj[1][idx], q_traj[2][idx], q_traj[3][idx], q_traj[4][idx], traj_q5q6[-1][0], traj_q5q6[-1][1] ] )
            else:
                traj.append( [q_traj[0][-1], q_traj[1][-1], q_traj[2][-1], q_traj[3][-1], q_traj[4][-1], traj_q5q6[idx][0], traj_q5q6[idx][1] ] )

        times = np.linspace(0.0, time, steps)

        return traj, times

    # get the ik solver index for given q
    def getJointSubspaceIndex(self, q):
        for ik_solver_idx in range(0, len(self.ik_solver_no_sing)):
            ik_solver_ok = True
            for i in range(0,7):
                if q[i] < self.q_min_no_sing[ik_solver_idx][i] or q[i] > self.q_max_no_sing[ik_solver_idx][i]:
                    ik_solver_ok = False
                    break
            if ik_solver_ok:
                return ik_solver_idx
        return None
