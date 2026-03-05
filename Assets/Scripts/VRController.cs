using System;
using UnityEngine;
using System.Threading.Tasks;
using System.Text;
using System.Net.Http;

[Serializable]
public class HandMessage
{
    public float[] wristPos;
    public float[] wristQuat;
    public float triggerState;
    public bool[] buttonState;
    public bool isHandTracking;   // true=人手追踪, false=手柄追踪
    public float[] jointPos;      // 24关节×3坐标=72个float，人手模式有效，手柄模式为空
    public HandMessage()
    {
        wristPos = new float[3];//position of the hand
        wristQuat = new float[4];//quaternion of the hand
        buttonState = new bool[5];//buttonState of B(Y)/A(X)/Thumbstick/IndexTrigger/HandTrigger
        isHandTracking = false;
        jointPos = null;
    }

    public void TransformToAlignSpace()
    {
        if (Calibration.instance)
        {
            Vector3 vector3 = Calibration.instance.GetPosition(new Vector3(wristPos[0], wristPos[1], wristPos[2]));
            wristPos[0] = vector3.x;
            wristPos[1] = vector3.y;
            wristPos[2] = vector3.z;
            Quaternion quaternion = Calibration.instance.GetRotation(new Quaternion(wristQuat[1], wristQuat[2], wristQuat[3], wristQuat[0]));
            wristQuat[0] = quaternion.w;
            wristQuat[1] = quaternion.x;
            wristQuat[2] = quaternion.y;
            wristQuat[3] = quaternion.z;

            // 对 24 个关节位置同步做坐标变换，保持与 wristPos 同一坐标系
            if (jointPos != null && jointPos.Length == 72)
            {
                for (int i = 0; i < 24; i++)
                {
                    Vector3 jp = Calibration.instance.GetPosition(new Vector3(
                        jointPos[i * 3], jointPos[i * 3 + 1], jointPos[i * 3 + 2]));
                    jointPos[i * 3]     = jp.x;
                    jointPos[i * 3 + 1] = jp.y;
                    jointPos[i * 3 + 2] = jp.z;
                }
            }
        }
    }
}

[Serializable]
public class Message
{
    public float timestamp;
    public HandMessage rightHand;
    public HandMessage leftHand;
    public float[] headPos;
    public float[] headQuat;
    public Message()
    {
        timestamp = Time.time;
        headPos = new float[3];
        headQuat = new float[4];
        rightHand = new HandMessage();
        leftHand = new HandMessage();
    }
    public void TransformToAlignSpace()
    {
        if (Calibration.instance)
        {
            Vector3 vector3 = Calibration.instance.GetPosition(new Vector3(headPos[0], headPos[1], headPos[2]));
            headPos[0] = vector3.x;
            headPos[1] = vector3.y;
            headPos[2] = vector3.z;
            Quaternion quaternion = Calibration.instance.GetRotation(new Quaternion(headQuat[1], headQuat[2], headQuat[3], headQuat[0]));
            headQuat[0] = quaternion.w;
            headQuat[1] = quaternion.x;
            headQuat[2] = quaternion.y;
            headQuat[3] = quaternion.z;

            rightHand.TransformToAlignSpace();
            leftHand.TransformToAlignSpace();
        }
    }
}

public class VRController : MonoBehaviour
{
    public static VRController instance;
    public string ip;
    public int port;
    HttpClient client = new HttpClient();
    public int Hz = 30;

    public TMPro.TextMeshProUGUI showText;

    public MyKeyboard keyboard;

    public Transform ovrhead;

    public Transform controller_right;
    public Transform controller_left;

    public OVRSkeleton skeleton_right;
    public OVRSkeleton skeleton_left;

    public static Message message;
    public bool LRinverse = false;

    protected void Start()
    {
        instance = this;
        showText.transform.parent.GetChild(1).GetComponent<TMPro.TextMeshProUGUI>().text = ip;
        message = new Message();
        Time.fixedDeltaTime = 1f / Hz;

        // 未手动绑定时自动从场景中查找 OVRSkeleton
        if (skeleton_right == null)
            skeleton_right = controller_right.GetComponentInChildren<OVRSkeleton>();
        if (skeleton_left == null)
            skeleton_left = controller_left.GetComponentInChildren<OVRSkeleton>();
        if (skeleton_right == null || skeleton_left == null)
        {
            // GetSkeletonType() 在部分 SDK 版本中不可访问，改用 GameObject 名称匹配
            var all = FindObjectsOfType<OVRSkeleton>();
            foreach (var s in all)
            {
                string n = s.gameObject.name.ToLower();
                if (skeleton_right == null && n.Contains("right"))
                    skeleton_right = s;
                if (skeleton_left == null && n.Contains("left"))
                    skeleton_left = s;
            }
        }
    }

    private void FixedUpdate()
    {
        CollectAndSend();
    }

    bool calibrationMode = false;
    bool cold = false;

    async void SwitchMode()
    {
        if (cold) return;
        cold = true;
        calibrationMode = !calibrationMode;
        Calibration.instance.SwitchAlign(calibrationMode);
        await Task.Delay(500);
        cold = false;
    }

    async void ClearImage()
    {
        if (cold) return;
        cold = true;
        VisualizationServer.instance.ClearImage();
        await Task.Delay(500);
        cold = false;
    }
    public void Update()
    {
        keyboard.transform.position = controller_right.position - new Vector3(0, 0.2f, 0);
        keyboard.transform.LookAt(Camera.main.transform);


        if (OVRInput.Get(OVRInput.RawButton.X) && OVRInput.Get(OVRInput.RawButton.A))
        {
            SwitchMode();
        }
        if (OVRInput.Get(OVRInput.RawButton.Y) && OVRInput.Get(OVRInput.RawButton.B))
        {
            ClearImage();
        }
        if (calibrationMode) return;

        if (OVRInput.GetDown(OVRInput.RawButton.LThumbstick))
        {
            keyboard.gameObject.SetActive(!keyboard.gameObject.activeSelf);
        }
    }

    public void CollectAndSend()
    {
        message.rightHand.wristPos[0] = controller_right.position.x;
        message.rightHand.wristPos[1] = controller_right.position.y;
        message.rightHand.wristPos[2] = controller_right.position.z;

        message.rightHand.wristQuat[0] = controller_right.rotation.w;
        message.rightHand.wristQuat[1] = controller_right.rotation.x;
        message.rightHand.wristQuat[2] = controller_right.rotation.y;
        message.rightHand.wristQuat[3] = controller_right.rotation.z;

        message.leftHand.wristPos[0] = controller_left.position.x;
        message.leftHand.wristPos[1] = controller_left.position.y;
        message.leftHand.wristPos[2] = controller_left.position.z;

        message.leftHand.wristQuat[0] = controller_left.rotation.w;
        message.leftHand.wristQuat[1] = controller_left.rotation.x;
        message.leftHand.wristQuat[2] = controller_left.rotation.y;
        message.leftHand.wristQuat[3] = controller_left.rotation.z;

        message.leftHand.triggerState = OVRInput.Get(OVRInput.Axis1D.PrimaryIndexTrigger);
        message.rightHand.triggerState = OVRInput.Get(OVRInput.Axis1D.SecondaryIndexTrigger);

        message.leftHand.buttonState[0] = OVRInput.Get(OVRInput.RawButton.Y);
        message.leftHand.buttonState[1] = OVRInput.Get(OVRInput.RawButton.X);
        message.leftHand.buttonState[2] = OVRInput.Get(OVRInput.RawButton.LThumbstick);
        message.leftHand.buttonState[3] = OVRInput.Get(OVRInput.RawButton.LIndexTrigger);
        message.leftHand.buttonState[4] = OVRInput.Get(OVRInput.RawButton.LHandTrigger);

        message.rightHand.buttonState[0] = OVRInput.Get(OVRInput.RawButton.B);
        message.rightHand.buttonState[1] = OVRInput.Get(OVRInput.RawButton.A);
        message.rightHand.buttonState[2] = OVRInput.Get(OVRInput.RawButton.RThumbstick);
        message.rightHand.buttonState[3] = OVRInput.Get(OVRInput.RawButton.RIndexTrigger);
        message.rightHand.buttonState[4] = OVRInput.Get(OVRInput.RawButton.RHandTrigger);

        // 追踪模式检测 + 关节数据采集
        bool rightIsHand = skeleton_right != null && skeleton_right.IsDataValid;
        bool leftIsHand  = skeleton_left  != null && skeleton_left.IsDataValid;
        message.rightHand.isHandTracking = rightIsHand;
        message.leftHand.isHandTracking  = leftIsHand;

        if (rightIsHand)
        {
            if (message.rightHand.jointPos == null || message.rightHand.jointPos.Length != 72)
                message.rightHand.jointPos = new float[72];
            int i = 0;
            foreach (var bone in skeleton_right.Bones)
            {
                if (i >= 24) break;
                if (bone.Transform == null) { i++; continue; }  // 防止 Transform 未初始化
                var p = bone.Transform.position;
                message.rightHand.jointPos[i * 3]     = p.x;
                message.rightHand.jointPos[i * 3 + 1] = p.y;
                message.rightHand.jointPos[i * 3 + 2] = p.z;
                i++;
            }
        }
        else { message.rightHand.jointPos = new float[0]; }  // JsonUtility 不序列化 null，用空数组代替

        if (leftIsHand)
        {
            if (message.leftHand.jointPos == null || message.leftHand.jointPos.Length != 72)
                message.leftHand.jointPos = new float[72];
            int i = 0;
            foreach (var bone in skeleton_left.Bones)
            {
                if (i >= 24) break;
                if (bone.Transform == null) { i++; continue; }  // 防止 Transform 未初始化
                var p = bone.Transform.position;
                message.leftHand.jointPos[i * 3]     = p.x;
                message.leftHand.jointPos[i * 3 + 1] = p.y;
                message.leftHand.jointPos[i * 3 + 2] = p.z;
                i++;
            }
        }
        else { message.leftHand.jointPos = new float[0]; }  // JsonUtility 不序列化 null，用空数组代替

        if (LRinverse)
        {
            var temp = message.leftHand;
            message.leftHand = message.rightHand;
            message.rightHand = temp;
        }

        message.headPos[0] = ovrhead.position.x;
        message.headPos[1] = ovrhead.position.y;
        message.headPos[2] = ovrhead.position.z;
        message.headQuat[0] = ovrhead.rotation.w;
        message.headQuat[1] = ovrhead.rotation.x;
        message.headQuat[2] = ovrhead.rotation.y;
        message.headQuat[3] = ovrhead.rotation.z;

        message.timestamp = Time.time;

        //transform to align space
        message.TransformToAlignSpace();

        string mes = JsonUtility.ToJson(message);
        byte[] bodyRaw = Encoding.UTF8.GetBytes(mes);
        string url = $"http://{ip}:{port}/unity";
        var content = new ByteArrayContent(bodyRaw);
        client.PostAsync(url, content);
    }

    public void RefreshIP(string ip)
    {
        this.ip = ip;
    }
}
