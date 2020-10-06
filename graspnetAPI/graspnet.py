__author__ = 'hsfang, mhgou, cxwang'
__version__ = '1.0'

# Interface for accessing the GraspNet-1Billion dataset.
# Description and part of the codes modified from MSCOCO api

# GraspNet is an open project for general object grasping that is continuously enriched.
# Currently we release GraspNet-1Billion, a large-scale benchmark for general object grasping,
# as well as other related areas (e.g. 6D pose estimation, unseen object segmentation, etc.).
# graspnetapi is a Python API that # assists in loading, parsing and visualizing the
# annotations in GraspNet. Please visit https://graspnet.net/ for more information on GraspNet,
# including for the data, paper, and tutorials. The exact format of the annotations
# is also described on the GraspNet website. For example usage of the graspnetapi
# please see graspnetapi_demo.ipynb. In addition to this API, please download both
# the GraspNet images and annotations in order to run the demo.

# An alternative to using the API is to load the annotations directly
# into Python dictionary
# Using the API provides additional utility functions. Note that this API
# supports both *grasping* and *6d pose* annotations. In the case of
# 6d poses not all functions are defined (e.g. collisions are undefined).

# The following API functions are defined:
#  GraspNet             - GraspNet api class that loads GraspNet annotation file and prepare data structures.
#  getSceneIds          - Get scene ids that satisfy given filter conditions.
#  getObjIds            - Get obj ids that satisfy given filter conditions.
#  getDataIds           - Get data ids that satisfy given filter conditions.
#  loadGraspLabels      - Load grasp labels with the specified object ids.
#  loadObjModels        - Load object 3d mesh model with the specified object ids.
#  loadCollisionLabels  - Load collision labels with the specified scene ids.
#  loadGrasp            - Load grasp labels with the specified scene and annotation id.
#  loadData             - Load data path with the specified data ids.
#  showObjGrasp         - Save visualization of the grasp pose of specified object ids.
#  showSceneGrasp       - Save visualization of the grasp pose of specified scene ids.
#  show6DPose           - Save visualization of the 6d pose of specified scene ids, project obj models onto pointcloud
# Throughout the API "ann"=annotation, "obj"=object, and "img"=image.

# GraspNet Toolbox.      version 1.0
# Data, paper, and tutorials available at:  https://graspnet.net/
# Code written by Hao-Shu Fang and Minghao Gou, 2020.
# Licensed under the none commercial CC4.0 license [see https://graspnet.net/about]

import os
import numpy as np
from tqdm import tqdm
import open3d as o3d
import cv2
import trimesh

from .grasp import Grasp, GraspGroup, RectGrasp, RectGraspGroup, RECT_GRASP_ARRAY_LEN
from .utils.utils import transform_points, parse_posevector
from .utils.xmlhandler import xmlReader

TOTAL_SCENE_NUM = 190
GRASP_HEIGHT = 0.02

def _isArrayLike(obj):
    return hasattr(obj, '__iter__') and hasattr(obj, '__len__')


class GraspNet():
    def __init__(self, root, camera='kinect', split='train'):
        '''
        **input**:

        - camera: string of type of camera: kinect or realsense

        - split: string of type of split of dataset: "all", "train", "test", "test_seen", "test_similar" or "test_novel"

        - sceneIDs: a list of scene ids of the dataset, split should be "user_define"
        '''

        assert camera in ['kinect', 'realsense'], 'camera should be kinect or realsense'
        assert split in ['all', 'train', 'test', 'test_seen', 'test_similar', 'test_novel'], 'split should be all/train/test/test_seen/test_similar/test_novel'
        self.root = root
        self.camera = camera
        self.split = split
        self.collisionLabels = {}

        if split == 'all':
            self.sceneIds = list(range(TOTAL_SCENE_NUM))
        elif split == 'train':
            self.sceneIds = list(range(100))
        elif split == 'test':
            self.sceneIds = list(range(100, 190))
        elif split == 'test_seen':
            self.sceneIds = list(range(100, 130))
        elif split == 'test_similar':
            self.sceneIds = list(range(130, 160))
        elif split == 'test_novel':
            self.sceneIds = list(range(160, 190))

        self.rgbPath = []
        self.depthPath = []
        self.segLabelPath = []
        self.metaPath = []
        self.rectLabelPath = []
        self.sceneName = []
        self.annId = []

        for i in tqdm(self.sceneIds, desc='Loading data path...'):
            for img_num in range(256):
                self.rgbPath.append(os.path.join(
                    root, 'scenes', 'scene_'+str(i).zfill(4), camera, 'rgb', str(img_num).zfill(4)+'.png'))
                self.depthPath.append(os.path.join(
                    root, 'scenes', 'scene_'+str(i).zfill(4), camera, 'depth', str(img_num).zfill(4)+'.png'))
                self.segLabelPath.append(os.path.join(
                    root, 'scenes', 'scene_'+str(i).zfill(4), camera, 'label', str(img_num).zfill(4)+'.png'))
                self.metaPath.append(os.path.join(
                    root, 'scenes', 'scene_'+str(i).zfill(4), camera, 'meta', str(img_num).zfill(4)+'.mat'))
                self.rectLabelPath.append(os.path.join(
                    root, 'scenes', 'scene_'+str(i).zfill(4), camera, 'rectangle_grasp', str(img_num).zfill(4)+'.npy'))
                self.sceneName.append('scene_'+str(i).zfill(4))
                self.annId.append(img_num)

        self.objIds = self.getObjIds(self.sceneIds)

    def __len__(self):
        return len(self.depthPath)

    def getSceneIds(self, objIds=None):
        '''
        **Input:**

        - objIds: int or list of int of the object ids.

        **Output:**

        - a list of int of the scene ids that contains **all** the objects.
        '''
        if objIds is None:
            return self.sceneIds
        assert _isArrayLike(objIds) or isinstance(objIds, int), 'objIds must be integer or a list/numpy array of integers'
        objIds = objIds if _isArrayLike(objIds) else [objIds]
        sceneIds = []
        for i in self.sceneIds:
            f = open(os.path.join(self.root, 'scenes', 'scene_' + str(i).zfill(4), 'object_id_list.txt'))
            idxs = [int(line.strip()) for line in f.readlines()]
            check = all(item in idxs for item in objIds)
            if check:
                sceneIds.append(i)
        return sceneIds

    def getObjIds(self, sceneIds=None):
        '''
        **Input:**

        - sceneIds: int or list of int of the scene ids.

        **Output:**

        - a list of int of the object ids in the given scenes.
        '''
        # get object ids in the given scenes
        if sceneIds is None:
            return self.objIds
        assert _isArrayLike(sceneIds) or isinstance(sceneIds, int), 'sceneIds must be an integer or a list/numpy array of integers'
        sceneIds = sceneIds if _isArrayLike(sceneIds) else [sceneIds]
        objIds = []
        for i in sceneIds:
            f = open(os.path.join(self.root, 'scenes', 'scene_' + str(i).zfill(4), 'object_id_list.txt'))
            idxs = [int(line.strip()) for line in f.readlines()]
            objIds = list(set(objIds+idxs))
        return objIds

    def getDataIds(self, sceneIds=None):
        '''
        **Input:**

        - sceneIds:int or list of int of the scenes ids.

        **Output:**

        - a list of int of the data ids. Data could be accessed by calling self.loadData(ids).
        '''
        # get index for datapath that contains the given scenes
        if sceneIds is None:
            return list(range(len(self.sceneName)))
        ids = []
        indexPosList = []
        for i in sceneIds:
            indexPosList += [ j for j in range(0,len(self.sceneName),256) if self.sceneName[j] == 'scene_'+str(i).zfill(4) ]
        for idx in indexPosList:
            ids += list(range(idx, idx+256))
        return ids

    def loadGraspLabels(self, objIds=None):
        '''
        **Input:**

        - objIds: int or list of int of the object ids.

        **Output:**

        - a dict of grasplabels of each object. 
        '''
        # load object-level grasp labels of the given obj ids
        objIds = self.objIds if objIds is None else objIds
        assert _isArrayLike(objIds) or isinstance(objIds, int), 'objIds must be an integer or a list/numpy array of integers'
        objIds = objIds if _isArrayLike(objIds) else [objIds]
        graspLabels = {}
        for i in tqdm(objIds, desc='Loading grasping labels...'):
            file = np.load(os.path.join(self.root, 'grasp_label', '{}_labels.npz'.format(str(i).zfill(3))))
            graspLabels[i] = (file['points'].astype(np.float32), file['offsets'].astype(np.float32), file['scores'].astype(np.float32))
        return graspLabels

    def loadObjModels(self, objIds=None):
        '''
        **Function:**

        - load object 3D models of the given obj ids

        **Input:**

        - objIDs: int or list of int of the object ids

        **Output:**

        - a list of open3d.geometry.PointCloud of the models
        '''
        objIds = self.objIds if objIds is None else objIds
        assert _isArrayLike(objIds) or isinstance(objIds, int), 'objIds must be an integer or a list/numpy array of integers'
        objIds = objIds if _isArrayLike(objIds) else [objIds]
        models = []
        for i in tqdm(objIds, desc='Loading objects...'):
            plyfile = os.path.join(self.root, 'models','%03d' % i, 'nontextured.ply')
            models.append(o3d.io.read_point_cloud(plyfile))
        return models

    def loadObjTrimesh(self, objIds=None):
        '''
        **Function:**

        - load object 3D trimesh of the given obj ids

        **Input:**

        - objIDs: int or list of int of the object ids

        **Output:**

        - a list of rimesh.Trimesh of the models
        '''
        objIds = self.objIds if objIds is None else objIds
        assert _isArrayLike(objIds) or isinstance(objIds, int), 'objIds must be an integer or a list/numpy array of integers'
        objIds = objIds if _isArrayLike(objIds) else [objIds]
        models = []
        for i in tqdm(objIds, desc='Loading objects...'):
            plyfile = os.path.join(self.root, 'models','%03d' % i, 'nontextured.ply')
            models.append(trimesh.load(plyfile))
        return models

    def loadCollisionLabels(self, sceneIds=None):
        '''
        **Input:**
        
        - sceneIds: int or list of int of the scene ids.

        **Output:**

        - dict of the collision labels.
        '''
        sceneIds = self.sceneIds if sceneIds is None else sceneIds
        assert _isArrayLike(sceneIds) or isinstance(sceneIds, int), 'sceneIds must be an integer or a list/numpy array of integers'
        sceneIds = sceneIds if _isArrayLike(sceneIds) else [sceneIds]
        collisionLabels = {}
        for sid in tqdm(sceneIds, desc='Loading collision labels...'):
            labels = np.load(os.path.join(self.root, 'collision_label','scene_'+str(sid).zfill(4),  'collision_labels.npz'))
            collisionLabel = []
            for j in range(len(labels)):
                collisionLabel.append(labels['arr_{}'.format(j)])
            collisionLabels['scene_'+str(sid).zfill(4)] = collisionLabel
        return collisionLabels

    def loadRGB(self, sceneId, camera, annId):
        '''
        **Input:**

        - sceneId: int of the scene index.
        
        - camera: string of type of camera, 'realsense' or 'kinect'

        - annId: int of the annotation index.

        **Output:**

        - numpy array of the rgb in RGB order.
        '''
        return cv2.cvtColor(cv2.imread(os.path.join(self.root, 'scenes', 'scene_%04d' % sceneId, camera, 'rgb', '%04d.png' % annId)), cv2.COLOR_BGR2RGB)

    def loadBGR(self, sceneId, camera, annId):
        '''
        **Input:**

        - sceneId: int of the scene index.
        
        - camera: string of type of camera, 'realsense' or 'kinect'

        - annId: int of the annotation index.

        **Output:**

        - numpy array of the rgb in BGR order.
        '''
        return cv2.imread(os.path.join(self.root, 'scenes', 'scene_%04d' % sceneId, camera, 'rgb', '%04d.png' % annId))

    def loadDepth(self, sceneId, camera, annId):
        '''
        **Input:**

        - sceneId: int of the scene index.
        
        - camera: string of type of camera, 'realsense' or 'kinect'

        - annId: int of the annotation index.

        **Output:**

        - numpy array of the depth with dtype = np.uint16
        '''
        return cv2.imread(os.path.join(self.root, 'scenes', 'scene_%04d' % sceneId, camera, 'depth', '%04d.png' % annId), cv2.IMREAD_UNCHANGED)
    
    def loadScenePointCloud(self, sceneId, camera, annId, align=False, format = 'open3d'):
        '''
        **Input:**

        - sceneId: int of the scene index.
        
        - camera: string of type of camera, 'realsense' or 'kinect'

        - annId: int of the annotation index.

        - aligh: bool of whether align to the table frame.

        **Output:**

        - open3d.geometry.PointCloud instance of the scene point cloud.

        - or tuple of numpy array of point locations and colors.
        '''
        colors = self.loadRGB(sceneId = sceneId, camera = camera, annId = annId).astype(np.float32) / 255.0
        depths = self.loadDepth(sceneId = sceneId, camera = camera, annId = annId)
        intrinsics = np.load(os.path.join(self.root, 'scenes', 'scene_%04d' % sceneId, camera, 'camK.npy'))
        fx, fy = intrinsics[0,0], intrinsics[1,1]
        cx, cy = intrinsics[0,2], intrinsics[1,2]
        s = 1000.0
        
        if align:
            camera_poses = np.load(os.path.join(self.root, 'scenes', 'scene_%04d' % sceneId, camera, 'camera_poses.npy'))
            camera_pose = camera_poses[annId]
            align_mat = np.load(os.path.join(self.root, 'scenes', 'scene_%04d' % sceneId, camera, 'cam0_wrt_table.npy'))
            camera_pose = align_mat.dot(camera_pose)

        xmap, ymap = np.arange(colors.shape[1]), np.arange(colors.shape[0])
        xmap, ymap = np.meshgrid(xmap, ymap)

        points_z = depths / s
        points_x = (xmap - cx) / fx * points_z
        points_y = (ymap - cy) / fy * points_z

        mask = (points_z > 0)
        points = np.stack([points_x, points_y, points_z], axis=-1)
        points = points[mask]
        colors = colors[mask]
        if align:
            points = transform_points(points, camera_pose)
        if format == 'open3d':
            cloud = o3d.geometry.PointCloud()
            cloud.points = o3d.utility.Vector3dVector(points)
            cloud.colors = o3d.utility.Vector3dVector(colors)
            return cloud
        elif format == 'numpy':
            return points, colors
        else:
            raise ValueError('Format must be either "open3d" or "numpy".')

    def loadSceneModel(self, sceneId, camera = 'kinect', annId = 0, align = False):
        '''
        **Input:**

        - sceneId: int of the scene index.
        
        - camera: string of type of camera, 'realsense' or 'kinect'

        - annId: int of the annotation index.

        - align: bool of whether align to the table frame.

        **Output:**

        - open3d.geometry.PointCloud list of the scene models.
        '''
        if align:
            camera_poses = np.load(os.path.join(self.root, 'scenes', 'scene_%04d' % sceneId, camera, 'camera_poses.npy'))
            camera_pose = camera_poses[annId]
            align_mat = np.load(os.path.join(self.root, 'scenes', 'scene_%04d' % sceneId, camera, 'cam0_wrt_table.npy'))
            camera_pose = np.matmul(align_mat,camera_pose)
        scene_reader = xmlReader(os.path.join(self.root, 'scenes', 'scene_%04d' % sceneId, camera, 'annotations', '%04d.xml'% annId))
        posevectors = scene_reader.getposevectorlist()
        obj_list = []
        mat_list = []
        model_list = []
        pose_list = []
        for posevector in posevectors:
            obj_idx, pose = parse_posevector(posevector)
            obj_list.append(obj_idx)
            mat_list.append(pose)

        for obj_idx, pose in zip(obj_list, mat_list):
            plyfile = os.path.join(self.root, 'models', '%03d'%obj_idx, 'nontextured.ply')
            model = o3d.io.read_point_cloud(plyfile)
            points = np.array(model.points)
            if align:
                pose = np.dot(camera_pose, pose)
            points = transform_points(points, pose)
            model.points = o3d.utility.Vector3dVector(points)
            model_list.append(model)
            pose_list.append(pose)
        return model_list

    def loadGrasp(self, sceneId, annId=0, format = '6d', camera='kinect', grasp_labels = None, collision_labels = None, fric_coef_thresh=0.4):
        '''
        **Input:**

        - sceneId: int of scene id.

        - annId: int of annotation id.

        - format: string of grasp format, '6d' or 'rect'.

        - camera: string of camera type, 'kinect' or 'realsense'.

        - grasp_labels: dict of grasp labels. Call self.loadGraspLabels if not given.

        - collision_labels: dict of collision labels. Call self.loadCollisionLabels if not given.

        - fric_coef_thresh: float of the frcition coefficient threshold of the grasp. 

        ** ATTENTION **

        the LOWER the friction coefficient is, the better the grasp is.

        **Output:**

        - a python dictionary. The key is the object id and the content is also a dict.
        
        The element of each dict gives the parameters of a grasp.
        '''
        import numpy as np
        assert format == '6d' or format == 'rect', 'format must be "6d" or "rect"'
        if format == '6d':
            from .utils.xmlhandler import xmlReader
            from .utils.utils import get_obj_pose_list, generate_views, get_model_grasps, transform_points
            from .utils.rotation import batch_viewpoint_params_to_matrix
            
            camera_poses = np.load(os.path.join(self.root,'scenes','scene_%04d' %(sceneId,),camera, 'camera_poses.npy'))
            camera_pose = camera_poses[annId]
            scene_reader = xmlReader(os.path.join(self.root,'scenes','scene_%04d' %(sceneId,),camera,'annotations','%04d.xml' %(annId,)))
            pose_vectors = scene_reader.getposevectorlist()

            obj_list,pose_list = get_obj_pose_list(camera_pose,pose_vectors)
            if grasp_labels is None:
                print('warning: grasp_labels are not given, calling self.loadGraspLabels to retrieve them')
                grasp_labels = self.loadGraspLabels(objIds = obj_list)
            if collision_labels is None:
                print('warning: collision_labels are not given, calling self.loadCollisionLabels to retrieve them')
                collision_labels = self.loadCollisionLabels(sceneId)

            num_views, num_angles, num_depths = 300, 12, 4
            template_views = generate_views(num_views)
            template_views = template_views[np.newaxis, :, np.newaxis, np.newaxis, :]
            template_views = np.tile(template_views, [1, 1, num_angles, num_depths, 1])

            collision_dump = collision_labels['scene_'+str(sceneId).zfill(4)]

            # grasp = dict()
            grasp_group = GraspGroup()
            for i, (obj_idx, trans) in enumerate(zip(obj_list, pose_list)):

                sampled_points, offsets, fric_coefs = grasp_labels[obj_idx]
                collision = collision_dump[i]
                point_inds = np.arange(sampled_points.shape[0])

                num_points = len(point_inds)
                target_points = sampled_points[:, np.newaxis, np.newaxis, np.newaxis, :]
                target_points = np.tile(target_points, [1, num_views, num_angles, num_depths, 1])
                views = np.tile(template_views, [num_points, 1, 1, 1, 1])
                angles = offsets[:, :, :, :, 0]
                depths = offsets[:, :, :, :, 1]
                widths = offsets[:, :, :, :, 2]

                mask1 = ((fric_coefs <= fric_coef_thresh) & (fric_coefs > 0) & ~collision)
                target_points = target_points[mask1]
                target_points = transform_points(target_points, trans)
                target_points = transform_points(target_points, np.linalg.inv(camera_pose))
                views = views[mask1]
                angles = angles[mask1]
                depths = depths[mask1]
                widths = widths[mask1]
                fric_coefs = fric_coefs[mask1]

                Rs = batch_viewpoint_params_to_matrix(-views, angles)
                Rs = np.matmul(trans[np.newaxis, :3, :3], Rs)
                Rs = np.matmul(np.linalg.inv(camera_pose)[np.newaxis,:3,:3], Rs)

                num_grasp = widths.shape[0]
                scores = (1.1 - fric_coefs).reshape(-1,1)
                widths = widths.reshape(-1,1)
                heights = GRASP_HEIGHT * np.ones((num_grasp,1))
                depths = depths.reshape(-1,1)
                rotations = Rs.reshape((-1,9))
                object_ids = obj_idx * np.ones((num_grasp,1), dtype=np.int32)

                obj_grasp_array = np.hstack([scores, widths, heights, depths, rotations, target_points, object_ids]).astype(np.float32)

                grasp_group.grasp_group_array = np.concatenate((grasp_group.grasp_group_array, obj_grasp_array))
            return grasp_group
        else:
            # 'rect'
            # for rectangle grasp, collision labels and grasp labels are not necessray. 
            ##################### OLD LABEL ################
            ############### MODIFICATION NEEDED ############
            rect_grasp_label = np.load(os.path.join(self.root,'scenes','scene_%04d' % sceneId,camera,'rectangle_grasp','%04d.npy' % annId))
            mask = rect_grasp_label[:,5] <= fric_coef_thresh
            rect_grasp_label = rect_grasp_label[mask]
            num_grasp = len(rect_grasp_label)
            rect_grasp = RectGraspGroup()
            rect_grasp.rect_grasp_group_array = np.zeros((num_grasp, RECT_GRASP_ARRAY_LEN), dtype = np.float32)
            rect_grasp.rect_grasp_group_array[:,:6] = rect_grasp_label
            rect_grasp.rect_grasp_group_array[:,5] = 1.1 - rect_grasp.rect_grasp_group_array[:,5]
            rect_grasp.rect_grasp_group_array[:,6] = np.ones((num_grasp))
            return rect_grasp

    def loadData(self, ids=None, *extargs):
        '''
        **Input:**

        - ids: int or list of int of the the data ids.

        - extargs: extra arguments. This function can also be called with loadData(sceneId, camera, annId)

        **Output:**

        - if ids is int, returns a tuple of data path

        - if ids is not specified or is a list, returns a tuple of data path lists
        '''
        if ids is None:
            return (self.rgbPath, self.depthPath, self.segLabelPath, self.metaPath, self.rectLabelPath, self.sceneName, self.annId)
        
        if len(extargs) == 0:
            if isinstance(ids, int):
                return (self.rgbPath[ids], self.depthPath[ids], self.segLabelPath[ids], self.metaPath[ids], self.rectLabelPath[ids], self.sceneName[ids], self.annId[ids])
            else:
                return ([self.rgbPath[id] for id in ids],
                    [self.depthPath[id] for id in ids],
                    [self.segLabelPath[id] for id in ids],
                    [self.metaPath[id] for id in ids],
                    [self.rectLabelPath[id] for id in ids],
                    [self.sceneName[id] for id in ids],
                    [self.annId[id] for id in ids])
        if len(extargs) == 2:
            sceneId = ids
            camera, annId = extargs
            rgbPath = os.path.join(self.root, 'scenes', 'scene_'+str(sceneId).zfill(4), camera, 'rgb', str(annId).zfill(4)+'.png')
            depthPath = os.path.join(self.root, 'scenes', 'scene_'+str(sceneId).zfill(4), camera, 'depth', str(annId).zfill(4)+'.png')
            segLabelPath = os.path.join(self.root, 'scenes', 'scene_'+str(sceneId).zfill(4), camera, 'label', str(annId).zfill(4)+'.png')
            metaPath = os.path.join(self.root, 'scenes', 'scene_'+str(sceneId).zfill(4), camera, 'meta', str(annId).zfill(4)+'.mat')
            rectLabelPath = os.path.join(self.root, 'scenes', 'scene_'+str(sceneId).zfill(4), camera, 'rectangle_grasp', str(annId).zfill(4)+'.npy')
            scene_name = 'scene_'+str(sceneId).zfill(4)
            return (rgbPath, depthPath, segLabelPath, metaPath, rectLabelPath, scene_name,annId)

    def showObjGrasp(self, objIds=[], numGrasp=10, th=0.5, saveFolder='save_fig', show=False):
        from .utils.vis import visObjGrasp
        objIds = objIds if _isArrayLike(objIds) else [objIds]
        if len(objIds) == 0:
            print('You need to specify object ids.')
            return 0

        if not os.path.exists(saveFolder):
            os.mkdir(saveFolder)
        for obj_id in objIds:
            visObjGrasp(self.root, obj_id, num_grasp=numGrasp,th=th, save_folder=saveFolder, show=show)

    def showSceneGrasp(self, sceneId, camera = 'kinect', annId = 0, format = '6d', numGrasp = 20, show_object = True, coef_fric_thresh = 0.1):
        '''
        **Input:**

        - sceneId: int of the scene index.

        - camera: string of the camera type, 'realsense' or 'kinect'.

        - annId: int of the annotation index.

        - format: int of the annotation type, 'rect' or '6d'.

        - numGrasp: int of the displayed grasp number, grasps will be randomly sampled.

        - coef_fric_thresh: float of the friction coefficient of grasps. 
        '''
        if format == '6d':
            geometries = []
            sceneGrasp = self.loadGrasp(sceneId = sceneId, annId = annId, camera = camera, format = '6d', grasp_thresh = coef_fric_thresh)
            sceneGrasp = sceneGrasp.random_sample(numGrasp = numGrasp)
            scenePCD = self.loadScenePointCloud(sceneId = sceneId, camera = camera, annId = annId, align = False)
            geometries.append(scenePCD)
            geometries += sceneGrasp.to_open3d_geometry_list()
            if show_object:
                objectPCD = self.loadSceneModel(sceneId = sceneId, camera = camera, annId = annId, align = False)
                geometries += objectPCD
            o3d.visualization.draw_geometries(geometries)
        elif format == 'rect':
            bgr = self.loadBGR(sceneId = sceneId, camera = camera, annId = annId)
            sceneGrasp = self.loadGrasp(sceneId = sceneId, camera = camera, annId = annId, format = 'rect', grasp_thresh = coef_fric_thresh)
            sceneGrasp = sceneGrasp.random_sample(numGrasp = numGrasp)
            img = sceneGrasp.to_opencv_image(bgr, num_grasp = numGrasp)
            cv2.imshow('Rectangle Grasps',img)
            cv2.waitKey(0)
            cv2.destroyAllWindows()

    def show6DPose(self, sceneIds, saveFolder='save_fig', show=False):
        from .utils.vis import vis6D
        sceneIds = sceneIds if _isArrayLike(sceneIds) else [sceneIds]
        if len(sceneIds) == 0:
            print('You need specify scene ids.')
            return 0
        if not os.path.exists(saveFolder):
            os.mkdir(saveFolder)
        for scene_id in sceneIds:
            scene_name = 'scene_'+str(scene_id).zfill(4)
            vis6D(self.root, scene_name, 0, self.camera,
                  align_to_table=True, save_folder=saveFolder, show=show)