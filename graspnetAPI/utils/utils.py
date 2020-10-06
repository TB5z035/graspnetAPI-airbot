import os
import open3d as o3d
import numpy as np
from PIL import Image
from transforms3d.euler import euler2mat

from .rotation import batch_viewpoint_params_to_matrix
from .xmlhandler import xmlReader

class CameraInfo():
    def __init__(self, width, height, fx, fy, cx, cy, scale):
        self.width = width
        self.height = height
        self.fx = fx
        self.fy = fy
        self.cx = cx
        self.cy = cy
        self.scale = scale

def get_camera_intrinsic(camera):
    '''
    **Input:**

    - camera: string of type of camera, "realsense" or "kinect".

    **Output:**

    - numpy array of shape (3, 3) of the camera intrinsic matrix.
    '''
    param = o3d.camera.PinholeCameraParameters()
    if camera == 'kinect':
        param.intrinsic.set_intrinsics(1280,720,631.55,631.21,638.43,366.50)
    elif camera == 'realsense':
        param.intrinsic.set_intrinsics(1280,720,927.17,927.37,651.32,349.62)
    intrinsic = param.intrinsic.intrinsic_matrix
    return intrinsic

def create_point_cloud_from_depth_image(depth, camera, organized=True):
    assert(depth.shape[0] == camera.height and depth.shape[1] == camera.width)
    xmap = np.arange(camera.width)
    ymap = np.arange(camera.height)
    xmap, ymap = np.meshgrid(xmap, ymap)
    points_z = depth / camera.scale
    points_x = (xmap - camera.cx) * points_z / camera.fx
    points_y = (ymap - camera.cy) * points_z / camera.fy
    cloud = np.stack([points_x, points_y, points_z], axis=-1)
    if not organized:
        cloud = cloud.reshape([-1, 3])
    return cloud

def generate_views(N, phi=(np.sqrt(5)-1)/2, center=np.zeros(3, dtype=np.float32), R=1):
    idxs = np.arange(N, dtype=np.float32)
    Z = (2 * idxs + 1) / N - 1
    X = np.sqrt(1 - Z**2) * np.cos(2 * idxs * np.pi * phi)
    Y = np.sqrt(1 - Z**2) * np.sin(2 * idxs * np.pi * phi)
    views = np.stack([X,Y,Z], axis=1)
    views = R * np.array(views) + center
    return views

def generate_scene_model(dataset_root, scene_name, anno_idx, return_poses=False, align=False, camera='realsense'):

    if align:
        camera_poses = np.load(os.path.join(dataset_root, 'scenes', scene_name, camera, 'camera_poses.npy'))
        camera_pose = camera_poses[anno_idx]
        align_mat = np.load(os.path.join(dataset_root, 'scenes', scene_name, camera, 'cam0_wrt_table.npy'))
        camera_pose = np.matmul(align_mat,camera_pose)
    print('Scene {}, {}'.format(scene_name, camera))
    scene_reader = xmlReader(os.path.join(dataset_root, 'scenes', scene_name, camera, 'annotations', '%04d.xml'%anno_idx))
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
        plyfile = os.path.join(dataset_root, 'models', '%03d'%obj_idx, 'nontextured.ply')
        model = o3d.io.read_point_cloud(plyfile)
        points = np.array(model.points)
        if align:
            pose = np.dot(camera_pose, pose)
        points = transform_points(points, pose)
        model.points = o3d.utility.Vector3dVector(points)
        model_list.append(model)
        pose_list.append(pose)

    if return_poses:
        return model_list, obj_list, pose_list
    else:
        return model_list

def generate_scene_pointcloud(dataset_root, scene_name, anno_idx, align=False, camera='kinect'):
    colors = np.array(Image.open(os.path.join(dataset_root, 'scenes', scene_name, camera, 'rgb', '%04d.png'%anno_idx)), dtype=np.float32) / 255.0
    depths = np.array(Image.open(os.path.join(dataset_root, 'scenes', scene_name, camera, 'depth', '%04d.png'%anno_idx)))
    intrinsics = np.load(os.path.join(dataset_root, 'scenes', scene_name, camera, 'camK.npy'))
    fx, fy = intrinsics[0,0], intrinsics[1,1]
    cx, cy = intrinsics[0,2], intrinsics[1,2]
    s = 1000.0
    
    if align:
        camera_poses = np.load(os.path.join(dataset_root, 'scenes', scene_name, camera, 'camera_poses.npy'))
        camera_pose = camera_poses[anno_idx]
        align_mat = np.load(os.path.join(dataset_root, 'scenes', scene_name, camera, 'cam0_wrt_table.npy'))
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

    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(points)
    cloud.colors = o3d.utility.Vector3dVector(colors)

    return cloud

def rotation_matrix(rx, ry, rz):
    Rx = np.array([[1,          0,           0],
                   [0, np.cos(rx), -np.sin(rx)],
                   [0, np.sin(rx),  np.cos(rx)]])
    Ry = np.array([[ np.cos(ry), 0, np.sin(ry)],
                   [          0, 1,          0],
                   [-np.sin(ry), 0, np.cos(ry)]])
    Rz = np.array([[np.cos(rz), -np.sin(rz), 0],
                   [np.sin(rz),  np.cos(rz), 0],
                   [         0,           0, 1]])
    R = Rz.dot(Ry).dot(Rx)
    return R

def transform_matrix(tx, ty, tz, rx, ry, rz):
    trans = np.eye(4)
    trans[:3,3] = np.array([tx, ty, tz])
    rot_x = np.array([[1,          0,           0],
                      [0, np.cos(rx), -np.sin(rx)],
                      [0, np.sin(rx),  np.cos(rx)]])
    rot_y = np.array([[ np.cos(ry), 0, np.sin(ry)],
                      [          0, 1,          0],
                      [-np.sin(ry), 0, np.cos(ry)]])
    rot_z = np.array([[np.cos(rz), -np.sin(rz), 0],
                      [np.sin(rz),  np.cos(rz), 0],
                      [         0,           0, 1]])
    trans[:3,:3] = rot_x.dot(rot_y).dot(rot_z)
    return trans

def matrix_to_dexnet_params(matrix):
    approach = matrix[:, 0]
    binormal = matrix[:, 1]
    axis_y = binormal
    axis_x = np.array([axis_y[1], -axis_y[0], 0])
    if np.linalg.norm(axis_x) == 0:
        axis_x = np.array([1, 0, 0])
    axis_x = axis_x / np.linalg.norm(axis_x)
    axis_y = axis_y / np.linalg.norm(axis_y)
    axis_z = np.cross(axis_x, axis_y)
    R = np.c_[axis_x, np.c_[axis_y, axis_z]]
    approach = R.T.dot(approach)
    cos_t, sin_t = approach[0], -approach[2]
    angle = np.arccos(cos_t)
    if sin_t < 0:
        angle = np.pi * 2 - angle
    return binormal, angle

def viewpoint_params_to_matrix(towards, angle):
    axis_x = towards
    axis_y = np.array([-axis_x[1], axis_x[0], 0])
    if np.linalg.norm(axis_y) == 0:
        axis_y = np.array([0, 1, 0])
    axis_x = axis_x / np.linalg.norm(axis_x)
    axis_y = axis_y / np.linalg.norm(axis_y)
    axis_z = np.cross(axis_x, axis_y)
    R1 = np.array([[1, 0, 0],
                   [0, np.cos(angle), -np.sin(angle)],
                   [0, np.sin(angle), np.cos(angle)]])
    R2 = np.c_[axis_x, np.c_[axis_y, axis_z]]
    matrix = R2.dot(R1)
    return matrix

def dexnet_params_to_matrix(binormal, angle):
    axis_y = binormal
    axis_x = np.array([axis_y[1], -axis_y[0], 0])
    if np.linalg.norm(axis_x) == 0:
        axis_x = np.array([1, 0, 0])
    axis_x = axis_x / np.linalg.norm(axis_x)
    axis_y = axis_y / np.linalg.norm(axis_y)
    axis_z = np.cross(axis_x, axis_y)
    R1 = np.array([[np.cos(angle), 0, np.sin(angle)],
                  [0, 1, 0],
                  [-np.sin(angle), 0, np.cos(angle)]])
    R2 = np.c_[axis_x, np.c_[axis_y, axis_z]]
    matrix = R2.dot(R1)
    return matrix

def transform_points(points, trans):
    ones = np.ones([points.shape[0],1], dtype=points.dtype)
    points_ = np.concatenate([points, ones], axis=-1)
    points_ = np.matmul(trans, points_.T).T
    return points_[:,:3]

def get_model_grasps(datapath):
    label = np.load(datapath)
    points = label['points']
    offsets = label['offsets']
    scores = label['scores']
    collision = label['collision']
    return points, offsets, scores, collision

def parse_posevector(posevector):
    mat = np.zeros([4,4],dtype=np.float32)
    alpha, beta, gamma = posevector[4:7]
    alpha = alpha / 180.0 * np.pi
    beta = beta / 180.0 * np.pi
    gamma = gamma / 180.0 * np.pi
    mat[:3,:3] = euler2mat(alpha, beta, gamma)
    mat[:3,3] = posevector[1:4]
    mat[3,3] = 1
    obj_idx = int(posevector[0])
    return obj_idx, mat

def create_mesh_box(width, height, depth, dx=0, dy=0, dz=0):
    box = o3d.geometry.TriangleMesh()
    vertices = np.array([[0,0,0],
                         [width,0,0],
                         [0,0,depth],
                         [width,0,depth],
                         [0,height,0],
                         [width,height,0],
                         [0,height,depth],
                         [width,height,depth]])
    vertices[:,0] += dx
    vertices[:,1] += dy
    vertices[:,2] += dz
    triangles = np.array([[4,7,5],[4,6,7],[0,2,4],[2,6,4],
                          [0,1,2],[1,3,2],[1,5,7],[1,7,3],
                          [2,3,7],[2,7,6],[0,4,1],[1,4,5]])
    box.vertices = o3d.utility.Vector3dVector(vertices)
    box.triangles = o3d.utility.Vector3iVector(triangles)
    return box

def create_table_cloud(width, height, depth, dx=0, dy=0, dz=0, grid_size=0.01):
    xmap = np.linspace(0, width, int(width/grid_size))
    ymap = np.linspace(0, depth, int(depth/grid_size))
    zmap = np.linspace(0, height, int(height/grid_size))
    xmap, ymap, zmap = np.meshgrid(xmap, ymap, zmap, indexing='xy')
    xmap += dx
    ymap += dy
    zmap += dz
    points = np.stack([xmap, ymap, zmap], axis=-1)
    points = points.reshape([-1, 3])
    # print('points',points.shape)
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(points)
    return cloud

def create_axis(length,grid_size = 0.01):
    num = int(length / grid_size)
    xmap = np.linspace(0,length,num)
    ymap = np.linspace(0,2*length,num)
    zmap = np.linspace(0,3*length,num)
    x_p = np.vstack([xmap.T,np.zeros((1,num)),np.zeros((1,num))])
    y_p = np.vstack([np.zeros((1,num)),ymap.T,np.zeros((1,num))])
    z_p = np.vstack([np.zeros((1,num)),np.zeros((1,num)),zmap.T])
    p = np.hstack([x_p,y_p,z_p])
    # print('p',p.shape)
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(p.T)
    return cloud

def plot_axis(R,center,length,grid_size = 0.01):
    num = int(length / grid_size)
    xmap = np.linspace(0,length,num)
    ymap = np.linspace(0,2*length,num)
    zmap = np.linspace(0,3*length,num)
    x_p = np.vstack([xmap.T,np.zeros((1,num)),np.zeros((1,num))])
    y_p = np.vstack([np.zeros((1,num)),ymap.T,np.zeros((1,num))])
    z_p = np.vstack([np.zeros((1,num)),np.zeros((1,num)),zmap.T])
    p = np.hstack([x_p,y_p,z_p])
    # print('p',p.shape)
    p = np.dot(R, p).T + center
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(p)
    return cloud

def plot_gripper_pro_max(center, R, width, depth, score=1):
    '''
        center: target point
        R: rotation matrix
    '''
    x, y, z = center
    height=0.004
    finger_width = 0.004
    tail_length = 0.04
    depth_base = 0.02
    
    color_r = score # red for high score
    color_b = 1 - score # blue for low score
    color_g = 0
    left = create_mesh_box(depth+depth_base+finger_width, finger_width, height)
    right = create_mesh_box(depth+depth_base+finger_width, finger_width, height)
    bottom = create_mesh_box(finger_width, width, height)
    tail = create_mesh_box(tail_length, finger_width, height)

    left_points = np.array(left.vertices)
    left_triangles = np.array(left.triangles)
    left_points[:,0] -= depth_base + finger_width
    left_points[:,1] -= width/2 + finger_width
    left_points[:,2] -= height/2

    right_points = np.array(right.vertices)
    right_triangles = np.array(right.triangles) + 8
    right_points[:,0] -= depth_base + finger_width
    right_points[:,1] += width/2
    right_points[:,2] -= height/2

    bottom_points = np.array(bottom.vertices)
    bottom_triangles = np.array(bottom.triangles) + 16
    bottom_points[:,0] -= finger_width + depth_base
    bottom_points[:,1] -= width/2
    bottom_points[:,2] -= height/2

    tail_points = np.array(tail.vertices)
    tail_triangles = np.array(tail.triangles) + 24
    tail_points[:,0] -= tail_length + finger_width + depth_base
    tail_points[:,1] -= finger_width / 2
    tail_points[:,2] -= height/2

    vertices = np.concatenate([left_points, right_points, bottom_points, tail_points], axis=0)
    vertices = np.dot(R, vertices.T).T + center
    triangles = np.concatenate([left_triangles, right_triangles, bottom_triangles, tail_triangles], axis=0)
    colors = np.array([ [color_r,color_g,color_b] for _ in range(len(vertices))])

    gripper = o3d.geometry.TriangleMesh()
    gripper.vertices = o3d.utility.Vector3dVector(vertices)
    gripper.triangles = o3d.utility.Vector3iVector(triangles)
    gripper.vertex_colors = o3d.utility.Vector3dVector(colors)
    return gripper


def find_scene_by_model_id(dataset_root, model_id_list):
    picked_scene_names = []
    scene_names = ['scene_'+str(i).zfill(4) for i in range(190)]
    for scene_name in scene_names:
        try:
            scene_reader = xmlReader(os.path.join(dataset_root, 'scenes', scene_name, 'kinect', 'annotations', '0000.xml'))
        except:
            continue
        posevectors = scene_reader.getposevectorlist()
        for posevector in posevectors:
            obj_idx, _ = parse_posevector(posevector)
            if obj_idx in model_id_list:
                picked_scene_names.append(scene_name)
                print(obj_idx, scene_name)
                break
    return picked_scene_names

def generate_scene(scene_idx, anno_idx, return_poses=False, align=False, camera='realsense'):
    camera_poses = np.load(os.path.join('scenes','scene_%04d' %(scene_idx,),camera, 'camera_poses.npy'))
    camera_pose = camera_poses[anno_idx]
    if align:
        align_mat = np.load(os.path.join('camera_poses', '{}_alignment.npy'.format(camera)))
        camera_pose = align_mat.dot(camera_pose)
    camera_split = 'data' if camera == 'realsense' else 'data_kinect'
    # print('Scene {}, {}'.format(scene_idx, camera_split))
    scene_reader = xmlReader(os.path.join(scenedir % (scene_idx, camera), 'annotations', '%04d.xml'%(anno_idx)))
    posevectors = scene_reader.getposevectorlist()
    obj_list = []
    mat_list = []
    model_list = []
    pose_list = []
    for posevector in posevectors:
        obj_idx, mat = parse_posevector(posevector)
        obj_list.append(obj_idx)
        mat_list.append(mat)

    for obj_idx, mat in zip(obj_list, mat_list):
        model = o3d.io.read_point_cloud(os.path.join(modeldir, '%03d'%obj_idx, 'nontextured.ply'))
        points = np.array(model.points)
        pose = np.dot(camera_pose, mat)
        points = transform_points(points, pose)
        model.points = o3d.utility.Vector3dVector(points)
        model_list.append(model)
        pose_list.append(pose)

    if return_poses:
        return model_list, obj_list, pose_list
    else:
        return model_list

def get_obj_pose_list(camera_pose, pose_vectors):
    import numpy as np
    obj_list = []
    mat_list = []
    pose_list = []
    for posevector in pose_vectors:
        obj_idx, mat = parse_posevector(posevector)
        obj_list.append(obj_idx)
        mat_list.append(mat)

    for obj_idx, mat in zip(obj_list, mat_list):
        pose = np.dot(camera_pose, mat)
        pose_list.append(pose)

    return obj_list, pose_list

# def scene_collision_detection(scene_idx, anno_idx, save_dir, sample_size=0.005, outlier=0.08, camera='realsense'):
#     print('scene {} started!'.format(scene_idx))
#     if not os.path.exists(save_dir):
#         os.makedirs(save_dir)
#     model_list, obj_list, pose_list = generate_scene(scene_idx, anno_idx, return_poses=True, align=True, camera=camera)
#     table = create_table_cloud(1.0, 0.05, 1.0, dx=-0.5, dy=-0.5, dz=0, grid_size=0.001)
#     num_views, num_angles, num_depths = 300, 12, 4
#     viewpoints = generate_views(num_views)
#     height = 0.02
#     depth_base = 0.02
#     finger_width = 0.01
#     collision_masks = []

#     # merge scene
#     scene = [np.array(table.points)]
#     for model in model_list:
#         scene.append(np.array(model.points))
#     scene = np.concatenate(scene, axis=0)

#     for i, (obj_idx, trans) in enumerate(zip(obj_list, pose_list)):
#         print(obj_idx)
#         points, offsets, _, collision = get_model_grasps('%s/%03d_labels.npz'%(labeldir, obj_idx))
#         # crop scene
#         scene_trans = transform_points(scene, np.linalg.inv(trans))
#         xmin, xmax = points[:,0].min(), points[:,0].max()
#         ymin, ymax = points[:,1].min(), points[:,1].max()
#         zmin, zmax = points[:,2].min(), points[:,2].max()
#         xlim = ((scene_trans[:,0] > xmin-outlier) & (scene_trans[:,0] < xmax+outlier))
#         ylim = ((scene_trans[:,1] > ymin-outlier) & (scene_trans[:,1] < ymax+outlier))
#         zlim = ((scene_trans[:,2] > zmin-outlier) & (scene_trans[:,2] < zmax+outlier))
#         workspace = scene_trans[xlim & ylim & zlim]
#         # sample workspace
#         o3cloud = o3d.PointCloud()
#         o3cloud.points = o3d.Vector3dVector(workspace)
#         o3cloud = o3d.voxel_down_sample(o3cloud, sample_size)
#         workspace = np.array(o3cloud.points, dtype=np.float32)
#         # print(workspace.shape[0])
#         # # remove empty grasp points
#         # min_dists = compute_min_dist(points, workspace)
#         # points_in_scene = (min_dists < 0.01)
        
#         collision_mask = collision.astype(np.bool)
#         for j, grasp_point in enumerate(points):
#             print('{}/{}'.format(j,len(points)))
#             # if not points_in_scene[j]:
#             #     collision_mask[j] = True
#             #     continue
#             grasp_angle = offsets[j, :, :, :, 0:1]
#             grasp_depth = offsets[j, :, :, :, 1:2]
#             grasp_width = offsets[j, :, :, :, 2:3]
#             batch_viewpoints = np.tile(viewpoints, [1,num_angles*num_depths]).reshape(-1,3)
#             batch_angle = grasp_angle.reshape(-1)
#             grasp_poses = batch_viewpoint_params_to_matrix(-batch_viewpoints, batch_angle)
#             target = np.expand_dims(workspace-grasp_point, 0)
#             target = np.matmul(target, grasp_poses)
#             target = target.reshape([num_views, num_angles, num_depths, -1, 3])
            
#             mask1 = ((target[:,:,:,:,2]>-height/2) & (target[:,:,:,:,2]<height/2))
#             mask2 = ((target[:,:,:,:,0]>-depth_base) & (target[:,:,:,:,0]<grasp_depth))
#             mask3 = (target[:,:,:,:,1]>-(grasp_width/2+finger_width))
#             mask4 = (target[:,:,:,:,1]<-grasp_width/2)
#             mask5 = (target[:,:,:,:,1]<(grasp_width/2+finger_width))
#             mask6 = (target[:,:,:,:,1]>grasp_width/2)
#             mask7 = ((target[:,:,:,:,0]>-(depth_base+finger_width)) & (target[:,:,:,:,0]<-depth_base))
#             left_mask = (mask1 & mask2 & mask3 & mask4)
#             right_mask = (mask1 & mask2 & mask5 & mask6)
#             bottom_mask = (mask1 & mask3 & mask5 & mask7)
#             mask = np.any((left_mask | right_mask | bottom_mask), axis=-1)
#             collision_mask[j] = (collision_mask[j] | mask)

#         collision_masks.append(collision_mask)

#     np.savez('{}/collision_labels.npz'.format(save_dir, scene_idx, camera), *collision_masks)
#     print('scene {} finished!'.format(scene_idx))


# Rectangle Grasp Generation

def batch_rgbdxyz_2_rgbxy_depth(points, camera):
    '''
    **Input:**

    - points: np.array(-1,3) of the points in camera frame

    - camera: string of the camera type

    **Output:**

    - coords: float of xy in pixel frame [-1, 2]

    - depths: float of the depths of pixel frame [-1]
    '''
    intrinsics = get_camera_intrinsic(camera)
    fx, fy = intrinsics[0,0], intrinsics[1,1]
    cx, cy = intrinsics[0,2], intrinsics[1,2]
    s = 1000.0
    depths = s * points[:,2] # point_z
    ###################################
    # x and y should be inverted here #
    ###################################
    # y = point[0] / point[2] * fx + cx 
    # x = point[1] / point[2] * fy + cy
    # cx = 640, cy = 360 
    coords_x = points[:,0] / points[:,2] * fx + cx
    coords_y = points[:,1] / points[:,2] * fy + cy
    coords = np.stack([coords_x, coords_y], axis=-1)
    return coords, depths

def get_batch_key_points(centers, Rs, widths):
    '''
    **Input:**

    - centers: np.array(-1,3) of the translation

    - Rs: np.array(-1,3,3) of the rotation matrix

    - widths: np.array(-1) of the grasp width

    **Output:**

    - key_points: np.array(-1,4,3) of the key point of the grasp
    '''
    import numpy as np
    depth_base = 0.02
    height = 0.02
    key_points = np.zeros((centers.shape[0],4,3),dtype = np.float32)
    key_points[:,:,0] -= depth_base
    key_points[:,1:,1] -= widths[:,np.newaxis] / 2
    key_points[:,2,2] += height / 2
    key_points[:,3,2] -= height / 2
    key_points = np.matmul(Rs, key_points.transpose(0,2,1)).transpose(0,2,1)
    key_points = key_points + centers[:,np.newaxis,:]
    return key_points

def batch_key_points_2_tuple(key_points, scores, object_ids, camera):
    '''
    **Input:**

    - key_points: np.array(-1,4,3) of grasp key points, definition is shown in key_points.png
    
    - scores: numpy array of batch grasp scores.

    - camera: string of 'realsense' or 'kinect'.

    **Output:**

    - np.array([center_x,center_y,open_x,open_y,height])
    '''
    import numpy as np
    centers, _ = batch_rgbdxyz_2_rgbxy_depth(key_points[:,0,:], camera)
    opens, _ = batch_rgbdxyz_2_rgbxy_depth(key_points[:,1,:], camera)
    lefts, _ = batch_rgbdxyz_2_rgbxy_depth(key_points[:,2,:], camera)
    rights, _ = batch_rgbdxyz_2_rgbxy_depth(key_points[:,3,:], camera)
    heights = np.linalg.norm(lefts - rights, axis=-1, keepdims=True)
    tuples = np.concatenate([centers, opens, heights, scores[:, np.newaxis], object_ids[:, np.newaxis]], axis=-1).astype(np.float32)
    return tuples