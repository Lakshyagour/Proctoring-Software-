import base64
import logging
from datetime import datetime

import cv2
import mediapipe
import numpy as np
from deepface import DeepFace
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files import File
from django.http.response import StreamingHttpResponse
from django.shortcuts import redirect
from django.shortcuts import render

from accounts.models import UserProfile
from teachers.models import TestObjective, TestInformation
from .camera import VideoCamera
from .models import ProctoringLog
from .models import TestResult

mp_face_detection = mediapipe.solutions.face_detection
mp_drawing = mediapipe.solutions.drawing_utils
face_detection = mp_face_detection.FaceDetection(
    model_selection=0, min_detection_confidence=0.5)


@login_required
def dashboard(request):
    request.session['test_id'] = None
    return render(request, 'students/dashboard.html')


@login_required
def test_login(request):
    if request.method == 'POST':
        user = request.user
        username = user.username
        test_id = request.POST['test_id']
        password = request.POST['pass']
        user_image = request.POST["image_hidden"]

        if not TestInformation.objects.filter(test_id=test_id).values("password"):
            messages.error(request, "Test_Id is not valid")
            return render(request, 'students/test-login.html')

        if password != TestInformation.objects.filter(test_id=test_id).values("password")[0]["password"]:
            messages.error(request, "Password didn't match!")
            return render(request, 'students/test-login.html')

        user = UserProfile.objects.filter(username=username)[0]
        logging.info("Username: ", user.username)
        imgdata1 = user.user_image
        imgdata2 = user_image
        np_arr_1 = np.frombuffer(base64.b64decode(imgdata1), np.uint8)
        np_arr_2 = np.frombuffer(base64.b64decode(imgdata2), np.uint8)
        image1 = cv2.imdecode(np_arr_1, cv2.COLOR_BGR2GRAY)
        image2 = cv2.imdecode(np_arr_2, cv2.COLOR_BGR2GRAY)
        models = ["VGG-Face", "Facenet", "Facenet512", "OpenFace", "DeepFace", "DeepID", "ArcFace", "Dlib", "SFace"]
        model_name = models[-1]
        img_result = DeepFace.verify(image1, image2, model_name=model_name, enforce_detection=False)
        logging.debug(f"Image verifiled  = {img_result}")
        if not img_result["verified"]:
            messages.error(request, "Bad Image Credentials")
            return render(request, 'students/test-login.html')
        request.session['test_id'] = test_id

        student_id = request.user.username
        result = TestResult.objects.filter(test_id=test_id, student_id=student_id)
        if result:
            messages.error(request, "Test already submitted")
            return render(request, 'students/test-login.html')

        return redirect("give_test_objective")
    return render(request, 'students/test-login.html')


@login_required
def give_test_objective(request):
    if request.method == "POST":
        marks = 0
        test_information = TestInformation.objects.filter(test_id=request.session['test_id'])
        objective_questions = TestObjective.objects.filter(test_id=request.session['test_id'])
        for question in objective_questions:
            ans = question.ans
            question_id = question.question_id
            selected_option = request.POST[question_id] if question_id in request.POST.keys() else None
            if not selected_option:
                continue
            if ans == selected_option:
                marks += question.marks
            else:
                marks -= test_information[0].neg_mark
        result = TestResult()
        result.test_id = request.session['test_id']
        result.student_id = request.user.username
        result.marks = marks
        result.save()
        return redirect("test_result")
    objective_questions = TestObjective.objects.filter(test_id=request.session['test_id'])
    context = {"objective_questions": objective_questions}
    return render(request, 'students/give-test-obj.html', context=context)


@login_required
def test_result(request):
    test_id = request.session['test_id']
    student_id = request.user.username
    result = TestResult.objects.filter(test_id = test_id,student_id = student_id)
    context = {"marks":result[0].marks}
    return render(request, "students/test-result.html",context= context)


@login_required
def give_test_subjective(request):
    return render(request, 'students/give-test-obj.html')


@login_required
def exam_history(request):
    return render(request, 'students/dashboard.html')


def gen(camera, username):
    count = 0
    while True:
        frame = camera.get_frame()
        # print(org_frame.shape)
        flag, frame, count = get_results(frame, count, username)
        if flag:
            frame = cv2.copyMakeBorder(frame, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=[0, 0, 255])
        frame_flip = cv2.flip(frame, 1)
        ret, frame = cv2.imencode('.jpg', frame_flip)

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame.tobytes() + b'\r\n\r\n')


def video_stream(request):
    return StreamingHttpResponse(gen(VideoCamera(), request.user.username),
                                 content_type='multipart/x-mixed-replace; boundary=frame')


def get_result(username, image, count):
    violate = False
    image.flags.writeable = False
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    results = face_detection.process(image)

    if type(results.detections) == type(None) or len(results.detections) != 1:  # or yl:
        now = datetime.now()
        curr_time = now.strftime("%H_%M_%S")
        if count > 10 and int(datetime.now().strftime('%S')) % 2 == 0:
            logging.info(f"Image Log saved {curr_time}")
            cv2.imwrite(f"media/live_proctor_log_images/{username}.png", image)
            proctoring_log = ProctoringLog()
            proctoring_log.test_id = "test_id"
            proctoring_log.flag = "person on in window or any other flag"
            proctoring_log.student_id = username
            with open(f'media/live_proctor_log_images/{username}.png', 'rb') as destination_file:
                proctoring_log.image.save(f"{curr_time}.jpg", File(destination_file))
            proctoring_log.save()

            violate = True
            count = 0
        count += 1
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    return image, violate, count


def get_results(frame, count, username):
    frame, violate, count = get_result(username=username, image=frame, count=count)
    return violate, frame, count
