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

from std_msgs.msg import *
from sensor_msgs.msg import *
from geometry_msgs.msg import *
from visualization_msgs.msg import *

import PyKDL
import math
import numpy as np
import copy
import random
import velmautils
from subprocess import call

import surfaceutils

from openravepy.misc import OpenRAVEGlobalArguments
import openraveinstance
from optparse import OptionParser

class MedialAxisTest:
    """
Class for medial axis computation test.
"""

    def __init__(self, pub_marker=None):
        self.pub_marker = pub_marker

    def spin(self):

        parser = OptionParser(description='Openrave Velma interface')
        OpenRAVEGlobalArguments.addOptions(parser)
        (options, leftargs) = parser.parse_args()
        self.env = OpenRAVEGlobalArguments.parseAndCreate(options)#,defaultviewer=True)
        self.openrave_robot = self.env.ReadRobotXMLFile('robots/barretthand_ros.robot.xml')

        link = self.openrave_robot.GetLink("right_HandFingerOneKnuckleThreeLink")
        col = link.GetCollisionData()
        vertices = col.vertices
        faces = col.indices

        print "sampling the surface..."
        points = surfaceutils.sampleMeshDetailedRays(vertices, faces, 0.001)
        print "surface has %s points"%(len(points))

#        vertices, faces = surfaceutils.readStl("klucz_gerda_ascii.stl", scale=1.0)
#        points = surfaceutils.sampleMeshDetailedRays(vertices, faces, 0.002)

        print len(points)

        with open('points.txt', 'w') as f:
            for pt in points:
                p = pt.pos
                f.write(str(p.x()) + ' ' + str(p.y()) + ' ' + str(p.z()) + '\n')

        call(["touch","out_surf.off"])
        call(["touch","out_axis.off"])
        call(["/home/dseredyn/code/cocone/tightcocone/tcocone-linux", "-m", "points.txt", "out"])

        calc_radius = False
        points_medial = []
        with open('out_axis.off', 'r') as f:
            header = f.readline()
            header_s = header.split()
            p_count = int(header_s[1])
            for i in range(0, p_count):
                line = f.readline()
                values = line.split()
                center = PyKDL.Vector(float(values[0]), float(values[1]), float(values[2]))

                if calc_radius:
                    radius = None
                    for pt in points:
                        dist = (center-pt.pos).Norm()
                        if radius == None or radius > dist:
                            radius = dist
                    points_medial.append([center, radius*2.0])
                else:
                    points_medial.append([center, 0.001])

        print len(points_medial)
#        m_id = 0
#        for p in points:
#            m_id = self.pub_marker.publishSinglePointMarker(PyKDL.Vector(p[0], p[1], p[2]), m_id, r=0, g=1, b=0, namespace='default', frame_id='world', m_type=Marker.CUBE, scale=Vector3(0.005, 0.005, 0.005), T=None)

#        m_id = 0
#        for p in points_medial:
#            m_id = self.pub_marker.publishSinglePointMarker(p[0], m_id, r=1, g=0, b=0, namespace='default', frame_id='world', m_type=Marker.SPHERE, scale=Vector3(p[1],p[1],p[1]), T=None)
        m_id = 0
        m_id = self.pub_marker.publishMultiPointsMarkerWithSize(points_medial, m_id, r=1, g=0, b=0, namespace='default', frame_id='world', m_type=Marker.SPHERE, T=None)
#        m_id = self.pub_marker.publishMultiPointsMarker(points_medial, m_id, r=1, g=0, b=0, namespace='default', frame_id='world', m_type=Marker.SPHERE, scale=Vector3(0.0005, 0.0005, 0.0005), T=None)
        rospy.sleep(1)

        

        exit(0)

if __name__ == '__main__':

    rospy.init_node('MedialAxisTest')

    pub_marker = velmautils.MarkerPublisher()
    task = MedialAxisTest(pub_marker)
    rospy.sleep(1)

    task.spin()


