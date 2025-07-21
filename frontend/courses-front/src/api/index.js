const API_BASE_URL = "http://localhost:8000";

export const fetchCourses = async () => {
  const response = await fetch(`${API_BASE_URL}/courses`);
  return response.json();
};

export const fetchCourseDetails = async (courseId) => {
  const response = await fetch(`${API_BASE_URL}/courses/${courseId}`);
  return response.json();
};

export const fetchGroups = async (courseId) => {
  const response = await fetch(`${API_BASE_URL}/courses/${courseId}/groups`);
  return response.json();
};

export const fetchLabs = async (courseId, groupId) => {
  const response = await fetch(
    `${API_BASE_URL}/courses/${courseId}/groups/${groupId}/labs`
  );
  return response.json();
};

export const registerAndCheck = async (courseId, groupId, formData) => {
  const response = await fetch(
    `${API_BASE_URL}/courses/${courseId}/groups/${groupId}/register`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(formData),
    }
  );

  return response.json();
};


export async function gradeLab(courseId, groupId, labId, github) {
  const encodedLabId = encodeURIComponent(labId);

  const response = await fetch(
    `/api/courses/${courseId}/groups/${groupId}/labs/${encodedLabId}/grade`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ github }),
    }
  );

  return response.json();
}

/*
export const checkPlagiarism = async (repoUrl, files, sensitivity) => {
  const response = await fetch(`${API_BASE_URL}/admin/plagiarism-check`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${localStorage.getItem('token')}`
    },
    body: JSON.stringify({ repoUrl, files, sensitivity }),
  });
  
  if (!response.ok) {
    const errorData = await response.json();
    throw new Error(errorData.message || 'Plagiarism check failed');
  }
  
  return response.json();
};

/*export const getPlagiarismConfig = async (courseId, labId) => {
  const response = await fetch(
    `${API_BASE_URL}/courses/${courseId}/labs/${labId}/plagiarism-config`
  );
  return response.json();
};*/