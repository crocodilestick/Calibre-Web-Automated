fetch('/user_profiles.json')
  .then(response => response.json())
  .then(usernameToImage => {
    var usernameElement = document.querySelector('#top_user .hidden-sm');
    if (usernameElement) {
      var username = usernameElement.textContent.trim();

      if (usernameToImage[username]) {
        var style = document.createElement('style');
        style.innerHTML = `
          .profileDrop > span:before {
            background-image: url(${usernameToImage[username]}) !important;
          }
          body.me > div.container-fluid > div.row-fluid > div.col-sm-10:before {
            background-image: url(${usernameToImage[username]}) !important;
          }
          .navbar > .container-fluid > .navbar-header > button.navbar-toggle:before {
            background-image: url(${usernameToImage[username]}) !important;
          }
        `;
        document.head.appendChild(style);
      }
    }
  });
